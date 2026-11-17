"""Create and qualify the bore/shaft fixture using the real FreeCAD runtime."""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from shutil import copyfile
import subprocess
from tempfile import TemporaryDirectory

import FreeCAD

from acceptance_oracle import FIXTURES, load
from stackopt.adapters.freecad import export_active
from stackopt.contracts import FREECAD_UNCONFIGURED
from stackopt.diagnostics import ContractError, ExitStatus
from stackopt.snapshot import load_problem


def dump(path, document):
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def make_fixture(path):
    doc = FreeCAD.newDocument("StackOptReference")
    try:
        blank = doc.addObject("Part::Cylinder", "BoreBlank")
        blank.Radius = 15
        blank.Height = 10
        tool = doc.addObject("Part::Cylinder", "BoreTool")
        tool.Label = "Ring cutting tool"
        tool.Height = 10
        bore = doc.addObject("Part::Cut", "Bore")
        bore.Base = blank
        bore.Tool = tool
        shaft = doc.addObject("Part::Cylinder", "Shaft")
        shaft.Label = "Reference shaft"
        shaft.Height = 10
        for obj, name, size in ((tool, "BoreDiameter", "20.1 mm"), (shaft, "ShaftDiameter", "2 cm")):
            obj.addProperty("App::PropertyLength", name, "StackOpt").setExpression("Radius", f"{name} / 2")
            setattr(obj, name, size)
        doc.recompute()
        assert bore.isValid() and bore.Shape.isValid() and bore.Shape.Volume > 0
        doc.saveAs(str(path))
    finally:
        FreeCAD.closeDocument(doc.Name)


def bound_case():
    case = load("manual-case.json")
    targets = {"bore": ("BoreTool", "BoreDiameter"), "shaft": ("Shaft", "ShaftDiameter")}
    for dimension in case["dimensions"]:
        name, prop = targets[dimension["logical_id"]]
        dimension["nominal"] = {"kind": "cad", "target": {
            "adapter": "freecad", "occurrence_path": [name],
            "configuration": FREECAD_UNCONFIGURED, "dimension_id": prop,
        }}
    return case


def command(python, *args, expected=0):
    result = subprocess.run(
        [str(python), "-B", "-m", "stackopt", *map(str, args)],
        capture_output=True, encoding="utf-8", timeout=60, check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
    return result


def capture_phase(python, output, case, phase, expected_values, expected_document):
    records_path = output / f"{phase}.records.json"
    export_active(case, records_path)
    records = read(records_path)
    assert [record["logical_id"] for record in records] == ["bore", "shaft"]
    assert [record["nominal"] for record in records] == [
        {"value": value, "unit": "mm"} for value in expected_values
    ]
    for record in records:
        source = record["source"]
        assert source["document"] == source["assembly"]
        assert Path(source["document"]["path"]) == expected_document
        assert source["document"]["state"] == "unknown"
        assert record["tolerance"] == {"status": "unavailable"}
    snapshot = output / f"{phase}.snapshot.json"
    result = command(python, "extract", "freecad", "--case", case, "--records", records_path, "--out", snapshot)
    assert "2 CAD bindings" in result.stdout and "cad.source_state" in result.stderr
    return snapshot


def check_failed_bindings(python, output, work):
    case_file = work / "wrong-bindings.json"
    case = bound_case()
    case["dimensions"][0]["nominal"]["target"]["occurrence_path"] = ["Ring cutting tool"]
    case["dimensions"][1]["nominal"]["target"]["dimension_id"] = "Angle"
    dump(case_file, case)
    records_file = output / "wrong-bindings.records.json"
    export_active(case_file, records_file)
    records = read(records_file)
    assert [record["status"] for record in records] == ["failed", "failed"]
    codes = [record["diagnostics"][0]["code"] for record in records]
    assert codes == ["cad.binding_missing", "cad.read_failed"]
    destination = work / "existing.snapshot.json"
    destination.write_bytes(b"previous snapshot")
    result = command(python, "extract", "freecad", "--case", case_file, "--records", records_file,
                     "--out", destination, expected=5)
    assert result.stdout == "" and all(code in result.stderr for code in codes)
    assert destination.read_bytes() == b"previous snapshot"
    return codes


def check_replay(python, output, work, snapshot, phase, manual, bounds, allocation_exit):
    assert load_problem(snapshot).problem == load_problem(manual).problem
    result_summary = {}
    for verb, status in (("analyze", 0), ("allocate", allocation_exit)):
        report_file = output / f"{phase}.{verb}.json"
        manual_report_file = work / "manual.report.json"
        result = command(python, verb, snapshot, "--json", report_file, expected=status)
        manual_result = command(python, verb, manual, "--json", manual_report_file, expected=status)
        assert result.stdout == manual_result.stdout == ""
        report, manual_report = read(report_file), read(manual_report_file)
        excluded = {"source_kind", "diagnostics"}
        assert {k: v for k, v in report.items() if k not in excluded} == {
            k: v for k, v in manual_report.items() if k not in excluded
        }
        baseline = report["baseline"]
        assert (baseline["lower_bound"]["value"], baseline["upper_bound"]["value"]) == bounds
        if verb == "allocate" and phase == "before":
            assert report["ranking"]["best_candidate_indices"] == [2]
            assert report["explanation"]["margins"]["maximum"]["margin_delta"] == "0.0100092"
        if verb == "allocate" and phase == "after":
            assert report["search"] == {"status": "infeasible", "total": 4, "evaluated": 4, "feasible": 0}
            assert report["closest"]["candidate"]["index"] == 3
        result_summary[verb] = {"exit": status, "report_sha256": digest(report_file)}
    return result_summary


def verify(python, output):
    output.mkdir(parents=True)
    fixture = output / "StackOptReference.FCStd"
    make_fixture(fixture)
    fixture_hash = digest(fixture)
    case = output / "case.json"
    dump(case, bound_case())
    with TemporaryDirectory() as directory:
        native = Path(directory).resolve() / fixture.name
        copyfile(fixture, native)
        doc = FreeCAD.openDocument(str(native))
        try:
            assert doc.getObject("BoreTool").Radius.Value == 10.05
            before = capture_phase(python, output, case, "before", ("20.1", "20.0"), native)
            before_hash = digest(before)
            failures = check_failed_bindings(python, output, native.parent)
            doc.getObject("BoreTool").BoreDiameter = "20.12 mm"
            try:
                export_active(case, native.parent / "unrecomputed.records.json")
            except ContractError as exc:
                assert exc.exit_status == ExitStatus.EXTRACTION_FAILED
                assert exc.diagnostic["code"] == "cad.session_invalid"
            else:
                raise AssertionError("The exporter accepted an unrecomputed document")
            doc.recompute()
            assert doc.getObject("BoreTool").Radius.Value == 10.06
            after = capture_phase(python, output, case, "after", ("20.12", "20.0"), native)
        finally:
            FreeCAD.closeDocument(doc.Name)
        assert digest(native) == fixture_hash

    assert not native.exists()
    assert digest(fixture) == fixture_hash
    manual = FIXTURES / "manual-case.json"
    edited_manual = deepcopy(load(manual.name))
    edited_manual["dimensions"][0]["nominal"]["length"]["value"] = "20.12"
    with TemporaryDirectory() as directory:
        work = Path(directory)
        edited_file = work / "edited-manual.json"
        dump(edited_file, edited_manual)
        result_before = check_replay(python, output, work, before, "before", manual, ("0.041143", "0.158927"), 0)
        result_after = check_replay(python, output, work, after, "after", edited_file, ("0.0611246", "0.1789454"), 6)
    assert digest(before) == before_hash
    dump(output / "observations.json", {
        "freecad_version": FreeCAD.Version(), "fixture_sha256": fixture_hash,
        "snapshot_sha256": {"before": before_hash, "after": digest(after)},
        "geometry_radius_mm": {"before": "10.05", "after": "10.06"},
        "snapshot_replay": {"before": result_before, "after": result_after},
        "failed_binding_codes": failures, "unrecomputed": "cad.session_invalid",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("python", type=Path, help="Regular Python with StackOpt importable")
    parser.add_argument("output", type=Path, help="New evidence directory")
    args = parser.parse_args()
    verify(args.python.resolve(), args.output.resolve())
    print("FreeCAD export, StackOpt extraction and offline parity checks passed.")
