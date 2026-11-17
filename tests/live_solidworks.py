"""Verify the production adapter on a disposable copy of the Chat 07 assembly."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
from tempfile import TemporaryDirectory

from stackopt.adapters.solidworks import extract_active
from stackopt.case import ExtractionError, cad_bindings, load_case, resolve_case
from stackopt.diagnostics import ContractError, ExitStatus
from stackopt.snapshot import write_snapshot
from verify_evidence import verify_replay


FIXTURE = Path(__file__).resolve().parents[1] / "spikes/solidworks_07/evidence"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_hashes(directory):
    return {path.name: sha256(path) for path in directory.iterdir() if path.suffix.upper() in {".SLDASM", ".SLDPRT"}}


def run_live(output):
    from probe import DEFAULT_INSTALL, Session, active_configuration, config_names
    from run_fixture import activate, close_fixture, occurrence, rebuild, set_tolerance, show_configuration

    session = Session(DEFAULT_INSTALL)
    assert session.app.GetDocumentCount() == 0, "Use a SOLIDWORKS desktop with all documents closed."
    case = load_case(FIXTURE / "case.json")
    bindings = cad_bindings(case, adapter="solidworks")
    assert bindings == read_json(FIXTURE / "bindings.json")
    bore_target = bindings[0]["target"]
    bore_id = bore_target["dimension_id"]
    hashes = fixture_hashes(FIXTURE / "fixture")
    try:
        extract_active(bindings)
    except ContractError as exc:
        assert exc.exit_status == ExitStatus.EXTRACTION_FAILED
        assert exc.diagnostic["code"] == "cad.session_invalid"
        no_assembly = exc.diagnostic
    else:
        raise AssertionError("Expected a diagnostic without an active assembly.")

    output.mkdir()
    with TemporaryDirectory(prefix="stackopt-09-live-") as work:
        native = copytree(FIXTURE / "fixture", Path(work) / "fixture")
        try:
            assembly_path = native / "Chat07-Reference.SLDASM"
            doc, errors, warnings = session.app.OpenDoc6(str(assembly_path), 2, 65, "", 0, 0)
            assert doc is not None and not errors, (errors, warnings)
            assembly = session.wrap("IModelDoc2", doc)
            assert Path(assembly.GetPathName()) == assembly_path
            for binding in bindings:
                component = occurrence(session, assembly, binding["target"])
                part = session.wrap("IModelDoc2", component.GetModelDoc2())
                assert Path(part.GetPathName()).parent == native, "SOLIDWORKS loaded a part outside the fixture copy."
            bore_component = occurrence(session, assembly, bore_target)
            bore = session.wrap("IModelDoc2", bore_component.GetModelDoc2())
            expected = read_json(FIXTURE / "reopened.json")["records"]
            before = extract_active(bindings)
            assert [record["logical_id"] for record in before] == ["bore", "shaft"]
            for record, prior in zip(before, expected, strict=True):
                assert record["nominal"] == prior["nominal"]
                assert record["tolerance"] == prior["tolerance"]
                source = record["source"]
                assert all(source[key] == prior["source"][key]
                           for key in ("occurrence_path", "dimension_id", "configuration", "assembly_configuration"))
                assert source["assembly"] == {"id": str(assembly_path), "path": str(assembly_path), "state": "saved"}
                part_path = native / Path(prior["source"]["document"]["path"]).name
                assert source["document"] == {"id": str(part_path), "path": str(part_path), "state": "saved"}
            assert Path(session.wrap("IModelDoc2", session.app.ActiveDoc).GetPathName()) == assembly_path
            original = output / "before.snapshot.json"
            write_snapshot(original, resolve_case(case, before))
            original_hash = sha256(original)

            # The driver owns all fixture mutations. The production entry point only reads.
            activate(session, bore)
            dimension = session.wrap("IDimension", bore.Parameter(bore_id))
            assert dimension.SetSystemValue3(0.02012, 3, config_names("Default")) == 0
            rebuild(bore)
            activate(session, assembly)
            rebuild(assembly)
            after = extract_active(bindings)
            assert [record["nominal"]["value"] for record in after] == ["0.02012", "0.02"]
            assert [record["tolerance"] for record in after] == [record["tolerance"] for record in before]
            assert after[0]["source"]["document"]["state"] == "modified"
            write_snapshot(output / "after.snapshot.json", resolve_case(case, after))
            assert sha256(original) == original_hash

            # The same part has a different nominal and tolerance in Alternate.
            bore_component.ReferencedConfiguration = "Alternate"
            rebuild(assembly)
            alternate_case = deepcopy(case)
            alternate_case["dimensions"][0]["nominal"]["target"]["configuration"] = "Alternate"
            alternate_bindings = cad_bindings(alternate_case, adapter="solidworks")
            assert active_configuration(session, bore).Name == "Default"
            switched = extract_active(alternate_bindings)
            assert active_configuration(session, bore).Name == "Default"
            assert switched[0]["nominal"] == {"value": "0.0209", "unit": "m"}
            assert switched[0]["tolerance"] == {"status": "unavailable"}
            try:
                resolve_case(alternate_case, switched)
            except ExtractionError as exc:
                assert exc.diagnostic["code"] == "cad.tolerance_unresolved"
            else:
                raise AssertionError("CAD-selected tolerance must fail when the configuration cannot be confirmed.")
            alternate_case["dimensions"][0]["tolerance"] = {
                "kind": "manual", "source_ref": "Synthetic Chat 07 Alternate trial",
                "deviations": expected[0]["tolerance"]["deviations"],
            }
            manual = resolve_case(alternate_case, switched)
            assert manual.problem["dimensions"][0]["tolerance_source"] == "manual"
            assert any(item["code"] == "cad.tolerance_unresolved" for item in manual.diagnostics)
            wrong_config, = extract_active(bindings[:1])
            assert wrong_config["diagnostics"][0]["code"] == "cad.binding_unavailable"

            activate(session, bore)
            show_configuration(session, bore, "Alternate")
            activate(session, assembly)
            aligned = extract_active(alternate_bindings)
            assert aligned[0]["tolerance"]["deviations"]["upper"]["value"] == "0.00004"
            occurrence(session, assembly, bore_target).ReferencedConfiguration = "Default"
            rebuild(assembly)

            matrix = {}
            for trial in read_json(FIXTURE / "tolerance-matrix.json"):
                activate(session, bore)
                show_configuration(session, bore, "Default")
                dimension = session.wrap("IDimension", bore.Parameter(bore_id))
                requested = trial["requested_deviations"]
                lower, upper = (None, None) if requested is None else (
                    float(requested["lower"]["value"]), float(requested["upper"]["value"]),
                )
                set_tolerance(session, dimension, trial["requested_type"], lower, upper)
                rebuild(bore)
                activate(session, assembly)
                rebuild(assembly)
                record, = extract_active(bindings[:1])
                assert record["tolerance"] == trial["records"][0]["tolerance"], trial["trial"]
                matrix[trial["trial"]] = record["tolerance"]

            missing = deepcopy(bindings[0])
            missing["target"]["dimension_id"] = "Missing@Sketch1"
            missing_dim, = extract_active([missing])
            assert missing_dim["diagnostics"][0]["code"] == "cad.binding_missing"
            shaft_component = occurrence(session, assembly, bindings[1]["target"])
            assert shaft_component.SetSuppression2(0) == 2
            suppressed, = extract_active(bindings[1:])
            assert suppressed["diagnostics"][0]["code"] == "cad.binding_unavailable"
            assert "suppressed" in suppressed["diagnostics"][0]["message"]
        finally:
            close_fixture(session, native)
        assert session.app.GetDocumentCount() == 0
        assert fixture_hashes(native) == hashes == fixture_hashes(FIXTURE / "fixture")

    observations = {
        "application_revision": session.app.RevisionNumber(), "process_id": session.app.GetProcessID(),
        "OpenDoc6": {"errors": errors, "warnings": warnings}, "native_fixture_sha256": hashes,
        "original_snapshot_sha256": original_hash,
        "configuration_switched": switched[0], "configuration_aligned": aligned[0],
        "tolerance_matrix": matrix,
        "failures": {"no_assembly": no_assembly, "wrong_configuration": wrong_config,
                     "missing_dimension": missing_dim, "suppressed_component": suppressed},
    }
    (output / "observations.json").write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
    print("Production adapter verified on SOLIDWORKS", observations["application_revision"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="New evidence directory for live run, existing for offline replay")
    parser.add_argument("--offline", action="store_true", help="Replay the captured snapshots after the fixture is gone")
    args = parser.parse_args()
    if not args.offline:
        run_live(args.directory)
    verify_replay(args.directory)
    observations = read_json(args.directory / "observations.json")
    assert sha256(args.directory / "before.snapshot.json") == observations["original_snapshot_sha256"]
    if args.offline:
        assert not any(name == "pythoncom" or name == "win32com" for name in sys.modules)
        print("Offline replay passed without loading CAD dependencies.")


if __name__ == "__main__":
    main()
