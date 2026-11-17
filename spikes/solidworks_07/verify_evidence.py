"""Validate Chat 07 captures and build or replay their snapshots without CAD."""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from stackopt.analysis import evaluate
from stackopt.case import cad_bindings, load_case, resolve_case
from stackopt.contract_validation import format_decimal_text
from stackopt.snapshot import replay_snapshot, write_snapshot


PROJECT = Path(__file__).resolve().parents[2]
REFERENCE = PROJECT / "examples/acceptance-v1"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def capture(directory, name):
    return read_json(directory / f"{name}.json")


def clearance(evaluation):
    return evaluation["lower_bound"]["value"], evaluation["upper_bound"]["value"]


def check_capture(directory):
    before = capture(directory, "before")
    after = capture(directory, "after")
    for run, expected in ((before, ["0.0201", "0.02"]), (after, ["0.02012", "0.02"])):
        assert run["application_revision"] == "34.2.1"
        assert [record["nominal"] for record in run["records"]] == [
            {"value": value, "unit": "m"} for value in expected
        ]
        assert all(row["GetSuppression2"] == 2 and row["GetType"] == 0 for row in run["raw"])
        assert {row["part_display_length_unit_code"] for row in run["raw"]} == {3}
        for record in run["records"]:
            assert record["tolerance"]["deviations"] == {
                "lower": {"value": "-0.000025", "unit": "m"},
                "upper": {"value": "0.000025", "unit": "m"},
            }
    assert after["records"][0]["source"]["document"]["state"] == "modified"
    unsaved = capture(directory, "unsaved-assembly")["records"]
    assert all(row["source"]["assembly"]["state"] == "unsaved" for row in unsaved)

    switched = capture(directory, "configuration-switched")
    assert switched["records"][0]["nominal"]["value"] == "0.0209"
    assert switched["raw"][0]["GetSystemValue3_current"]["value"] == "0.02012"
    assert switched["records"][0]["tolerance"] == {"status": "unavailable"}
    assert switched["raw"][0]["native_tolerance"]["values"]["GetMaxValue2"]["value"] == "0.000025"
    aligned = capture(directory, "configuration-aligned")["records"][0]
    assert aligned["tolerance"]["deviations"]["upper"]["value"] == "0.00004"

    bad = capture(directory, "wrong-targets")["records"]
    assert [row["diagnostics"][0]["code"] for row in bad] == ["cad.binding_unavailable", "cad.binding_missing"]
    suppressed = capture(directory, "suppressed-shaft")
    assert suppressed["raw"][1]["GetSuppression2"] == 0
    assert suppressed["records"][1]["diagnostics"][0]["code"] == "cad.binding_unavailable"
    reopened = capture(directory, "reopened")["records"]
    assert [record["nominal"] for record in reopened] == [record["nominal"] for record in before["records"]]

    expected_tolerances = {
        "none": ("missing", 1, 1, None), "basic": ("unsupported", 1, 1, None),
        "bilateral_asymmetric": ("supported", 0, 0, ("-0.000013", "0.000031")),
        "bilateral_positive_only": ("supported", 0, 0, ("0.0", "0.000031")),
        "limit": ("supported", 0, 0, ("-0.000014", "0.000032")),
        "symmetric": ("supported", 1, 0, ("-0.000016", "0.000016")),
        "minimum": ("unsupported", 1, 1, None), "maximum": ("unsupported", 1, 1, None),
    }
    observations = {row["trial"]: row for row in capture(directory, "tolerance-matrix")}
    assert observations.keys() == expected_tolerances.keys()
    for name, (status, lower_status, upper_status, deviations) in expected_tolerances.items():
        trial = observations[name]
        tolerance = trial["records"][0]["tolerance"]
        assert tolerance["status"] == status and tolerance["native_type"] == trial["requested_type"]
        assert tolerance["native_status"] == {"GetMinValue2": lower_status, "GetMaxValue2": upper_status}
        if deviations is None:
            assert "deviations" not in tolerance
        else:
            assert tuple(tolerance["deviations"][side]["value"] for side in ("lower", "upper")) == deviations


def build_snapshots(directory):
    case = load_case(REFERENCE / "manual-case.json")
    case["case_id"] = "chat07-live-reference-bore-shaft"
    bindings = capture(directory, "bindings")
    targets = {binding["logical_id"]: binding["target"] for binding in bindings}
    # The authored model, requirements, callouts and options remain benchmark
    # assumptions. The two measured nominals and tolerances come from CAD.
    for dimension in case["dimensions"]:
        dimension["nominal"] = {"kind": "cad", "target": targets[dimension["logical_id"]]}
        dimension["tolerance"] = {"kind": "cad"}
    assert list(cad_bindings(case, adapter="solidworks")) == bindings
    case_path = directory / "case.json"
    with case_path.open("x", encoding="utf-8") as stream:
        json.dump(case, stream, indent=2)
        stream.write("\n")

    original = directory / "before.snapshot.json"
    write_snapshot(original, resolve_case(case, capture(directory, "before")["records"]))
    before_bytes = original.read_bytes()
    write_snapshot(directory / "after.snapshot.json", resolve_case(case, capture(directory, "after")["records"]))
    assert original.read_bytes() == before_bytes


def verify_replay(directory):
    expected = tuple(map(Fraction, read_json(REFERENCE / "reference.json")["baseline"]["envelope_mm"]))
    delta = Fraction("0.020")
    alpha = Fraction("0.000023")
    edited_expected = (expected[0] + delta * (1 - 40 * alpha),
                       expected[1] + delta * (1 + 40 * alpha))
    original = directory / "before.snapshot.json"
    before_bytes = original.read_bytes()
    before = evaluate(replay_snapshot(original).problem)
    after = evaluate(replay_snapshot(directory / "after.snapshot.json").problem)
    assert clearance(before) == expected
    assert clearance(after) == edited_expected
    assert before == evaluate(replay_snapshot(original).problem)
    assert original.read_bytes() == before_bytes
    for label, bounds in (("before", expected), ("after", edited_expected)):
        print(label, "envelope in mm", *(format_decimal_text(value) for value in bounds))
    print("Original snapshot SHA-256", hashlib.sha256(before_bytes).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--build-snapshots", action="store_true")
    args = parser.parse_args()
    check_capture(args.directory)
    if args.build_snapshots:
        build_snapshots(args.directory)
    verify_replay(args.directory)


if __name__ == "__main__":
    main()
