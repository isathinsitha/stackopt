"""Capture production CLI snapshots and verify offline replay of the Chat 07 fixture."""

import argparse
from fractions import Fraction
from importlib.metadata import requires
from importlib.util import find_spec
import json
import os
from pathlib import Path
from shutil import copytree
import subprocess
import sys
from tempfile import TemporaryDirectory

from acceptance_oracle import load
from live_solidworks import FIXTURE, fixture_hashes, read_json, sha256


def command(launcher, *args, expected=0):
    result = subprocess.run(
        [*launcher, *map(str, args)], capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"}, timeout=60, check=False,
    )
    assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
    return {"exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def run_live(output):
    from probe import DEFAULT_INSTALL, Session, config_names
    from run_fixture import activate, close_fixture, occurrence, rebuild

    session = Session(DEFAULT_INSTALL)
    assert session.app.GetDocumentCount() == 0, "Close open SOLIDWORKS documents before the live fixture run."
    assert session.app.RevisionNumber() == "34.2.1", "Use the qualified SOLIDWORKS installation."
    launcher = [str(Path(sys.executable).with_name("stackopt.exe"))]
    bindings = read_json(FIXTURE / "bindings.json")
    expected_records = read_json(FIXTURE / "reopened.json")["records"]
    source_hashes = fixture_hashes(FIXTURE / "fixture")
    output.mkdir()
    before = output / "before.snapshot.json"
    after = output / "after.snapshot.json"
    args = ("extract", "solidworks", "--active", "--case", FIXTURE / "case.json", "--out")
    missing = command(launcher, *args, before, expected=5)
    assert missing["stdout"] == "" and "cad.session_invalid" in missing["stderr"]
    assert not before.exists()
    with TemporaryDirectory(prefix="stackopt-10-fixture-") as temp:
        native = copytree(FIXTURE / "fixture", Path(temp) / "fixture")
        try:
            assembly_path = native / "Chat07-Reference.SLDASM"
            doc, errors, warnings = session.app.OpenDoc6(str(assembly_path), 2, 65, "", 0, 0)
            assert doc is not None and not errors, (errors, warnings)
            assembly = session.wrap("IModelDoc2", doc)
            assert Path(assembly.GetPathName()).resolve() == assembly_path.resolve()
            parts = []
            for binding, prior in zip(bindings, expected_records, strict=True):
                component = occurrence(session, assembly, binding["target"])
                part = session.wrap("IModelDoc2", component.GetModelDoc2())
                expected_path = native / Path(prior["source"]["document"]["path"]).name
                assert Path(part.GetPathName()).resolve() == expected_path.resolve()
                parts.append(part)
            activate(session, assembly)
            original_run = command(launcher, *args, before)
            assert "2 CAD bindings" in original_run["stdout"] and original_run["stderr"] == ""
            original_hash = sha256(before)
            originals = read_json(before)["extraction_records"]
            for record, prior in zip(originals, expected_records, strict=True):
                for key in ("occurrence_path", "dimension_id", "configuration", "assembly_configuration"):
                    assert record["source"][key] == prior["source"][key]
                assert record["nominal"] == prior["nominal"] and record["tolerance"] == prior["tolerance"]
                assert record["source"]["application_version"] == "34.2.1"

            bore = parts[0]
            activate(session, bore)
            dimension = session.wrap("IDimension", bore.Parameter(bindings[0]["target"]["dimension_id"]))
            assert dimension.SetSystemValue3(0.02012, 3, config_names("Default")) == 0
            rebuild(bore)
            activate(session, assembly)
            rebuild(assembly)
            revised_run = command(launcher, *args, after)
            assert "2 CAD bindings" in revised_run["stdout"] and "cad.source_state" in revised_run["stderr"]
            revised = read_json(after)["extraction_records"]
            assert [record["nominal"] for record in revised] == [
                {"value": "0.02012", "unit": "m"}, {"value": "0.02", "unit": "m"},
            ]
            assert [record["tolerance"] for record in revised] == [record["tolerance"] for record in originals]
            assert revised[0]["source"]["document"]["state"] == "modified"
            assert sha256(before) == original_hash
        finally:
            close_fixture(session, native)
        assert session.app.GetDocumentCount() == 0
        assert source_hashes == fixture_hashes(native) == fixture_hashes(FIXTURE / "fixture")

    evidence = {
        "application_revision": session.app.RevisionNumber(),
        "open_document": {"errors": errors, "warnings": warnings},
        "native_fixture_sha256": source_hashes,
        "original_snapshot_sha256": original_hash,
        "edited_snapshot_sha256": sha256(after),
        "extract": {"no_active_assembly": missing, "original": original_run, "edited": revised_run},
    }
    (output / "observations.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Installed CLI captured both live snapshots on SOLIDWORKS", evidence["application_revision"])


def run_offline(output):
    assert not requires("stackopt")
    for module in ("win32com", "pythoncom", "pywintypes"):
        assert find_spec(module) is None, f"{module} is installed in the replay environment."
    observations = read_json(output / "observations.json")
    reference = load("reference.json")["candidates"][0]
    launcher = [str(Path(sys.executable).with_name("stackopt.exe"))]
    module_launcher = [sys.executable, "-I", "-m", "stackopt"]
    evidence = {"python": sys.version, "interpreter": sys.executable, "operations": {}}
    for phase, digest_key, bore_delta in (
        ("before", "original_snapshot_sha256", Fraction(0)),
        ("after", "edited_snapshot_sha256", Fraction("0.020")),
    ):
        snapshot = output / f"{phase}.snapshot.json"
        for record in read_json(snapshot)["extraction_records"]:
            for document in ("assembly", "document"):
                assert not Path(record["source"][document]["path"]).exists()
        evidence["operations"][phase] = {}
        for verb in ("analyze", "allocate"):
            result = output / f"{phase}.{verb}.json"
            status = 6 if phase == "after" and verb == "allocate" else 0
            report_run = command(launcher, verb, snapshot, "--json", result, expected=status)
            assert report_run["stdout"] == ""
            if phase == "after":
                assert "warning [cad.source_state]" in report_run["stderr"]
            else:
                assert report_run["stderr"] == ""
            checked = result.read_bytes()
            assert command(module_launcher, verb, snapshot, "--json", result, expected=status) == report_run
            assert result.read_bytes() == checked
            report = read_json(result)
            assert report["source_kind"] == "snapshot"
            assert report["kind"] == {"analyze": "analysis_result", "allocate": "allocation_result"}[verb]
            baseline = report["baseline"]
            for side, endpoint, index, factor in (
                ("lower", "cold", 0, "0.99908"), ("upper", "hot", 1, "1.00092"),
            ):
                trace = baseline[f"{side}_bound"]
                delta = bore_delta * Fraction(factor)
                assert Fraction(trace["value"]) == Fraction(reference[f"{endpoint}_bounds_mm"][index]) + delta
                bore, shaft = reference[f"{side}_signed_terms_mm"]
                assert [Fraction(term["contribution"]) for term in trace["terms"]] == [
                    Fraction(bore) + delta, Fraction(shaft),
                ]
            assert not baseline["meets_requirement"]
            if verb == "allocate" and phase == "before":
                assert report["ranking"]["best_candidate_indices"] == [2]
                assert report["explanation"]["margins"]["maximum"]["margin_delta"] == "0.0100092"
            if verb == "allocate" and phase == "after":
                assert report["search"] == {"status": "infeasible", "total": 4, "evaluated": 4, "feasible": 0}
                assert report["closest"]["candidate"]["index"] == 3
            evidence["operations"][phase][verb] = {**report_run, "report_sha256": sha256(result)}
        assert sha256(snapshot) == observations[digest_key]

    with TemporaryDirectory() as directory:
        destination = Path(directory) / "preserved.snapshot.json"
        destination.write_bytes(b"existing snapshot")
        unavailable = command(
            launcher, "extract", "solidworks", "--active", "--case", FIXTURE / "case.json",
            "--out", destination, expected=4,
        )
        assert unavailable["stdout"] == "" and "cad.unavailable" in unavailable["stderr"]
        assert destination.read_bytes() == b"existing snapshot"
    evidence["unavailable"] = unavailable
    (output / "replay.observations.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Both installed launchers reproduced byte-identical reports without pywin32.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="New live capture directory or existing directory for replay")
    parser.add_argument("--offline", action="store_true", help="Replay the capture from a clean installation")
    args = parser.parse_args()
    verify = run_offline if args.offline else run_live
    verify(args.directory.resolve())


if __name__ == "__main__":
    main()
