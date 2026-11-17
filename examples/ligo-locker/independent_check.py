"""Check the published drawing endpoints without importing StackOpt.

Run after installing StackOpt in this Python environment. Decimal arithmetic
uses the drawing's full pin diameter, independently of the radius-based case.
"""

import argparse
from copy import deepcopy
from decimal import Decimal
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent
INCH = Decimal("25.4")
# D047935-v4, spherical diameter, and D1000860-v2/v1, small bore.
PIN_LIMITS = (Decimal("1.4995"), Decimal("1.5000"))
BORE_LIMITS = (
    (Decimal("1.5005"), Decimal("1.5010")),
    (Decimal("1.5000"), Decimal("1.5020")),
)


def run_report(verb, source, destination):
    completed = subprocess.run(
        [sys.executable, "-I", "-m", "stackopt", verb, str(source),
         "--json", str(destination)],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{verb} failed with exit {completed.returncode}\n{completed.stderr}")
    return json.loads(destination.read_text(encoding="utf-8"))


def check_evaluation(actual, expected):
    assert Decimal(actual["lower_bound"]["value"]) == expected["lower_mm"]
    assert Decimal(actual["upper_bound"]["value"]) == expected["upper_mm"]
    assert Decimal(actual["margins"]["minimum"]) == expected["minimum_margin_mm"]
    assert Decimal(actual["margins"]["maximum"]) == expected["maximum_margin_mm"]
    assert actual["meets_requirement"] == expected["meets_study_criterion"]
    assert actual["limiting_side"] == expected["limiting_side"]
    for side in ("lower", "upper"):
        bound = actual[f"{side}_bound"]
        assert Decimal(bound["temperature"]) == 20
        assert sum(Decimal(term["contribution"]) for term in bound["terms"]) == expected[f"{side}_mm"]


def main():
    if not __debug__:
        sys.exit("This check uses assert statements. Run it without python -O.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=HERE / "cad.snapshot.json")
    args = parser.parse_args()
    case = json.loads((HERE / "case.json").read_text(encoding="utf-8"))
    minimum = (BORE_LIMITS[0][0] - PIN_LIMITS[1]) * INCH
    maximum = (BORE_LIMITS[0][1] - PIN_LIMITS[0]) * INCH
    assert all(value["unit"] == "in" for value in (
        case["requirement"]["minimum"], case["requirement"]["maximum"],
    ))
    assert case["model"] == {
        "kind": "linear_free_expansion", "reference": {"value": "20", "unit": "degC"},
        "operating_min": {"value": "20", "unit": "degC"},
        "operating_max": {"value": "20", "unit": "degC"},
    }
    for dimension in case["dimensions"]:
        assert dimension["alpha"] == {"value": "0", "unit": "1/K"}
        assert dimension["nominal"]["length"]["unit"] == "in"
        assert all(value["unit"] == "in" for value in dimension["tolerance"]["deviations"].values())
    assert case["requirement"]["id"] == "study-preserve-v2-size-envelope"
    assert Decimal(case["requirement"]["minimum"]["value"]) * INCH == minimum
    assert Decimal(case["requirement"]["maximum"]["value"]) * INCH == maximum
    bore, radius = case["dimensions"]
    assert Decimal(bore["nominal"]["length"]["value"]) == BORE_LIMITS[0][0]
    radius_nominal = Decimal(radius["nominal"]["length"]["value"])
    assert tuple(2 * (radius_nominal + Decimal(radius["tolerance"]["deviations"][side]["value"]))
                 for side in ("lower", "upper")) == PIN_LIMITS
    assert case["chain"]["terms"] == [
        {"logical_id": "sleeve-bore", "coefficient": "1"},
        {"logical_id": "pin-sphere-radius", "coefficient": "-2"},
    ]
    options = case["option_groups"][0]["options"]
    assert len(options) == len(BORE_LIMITS)
    expected = []
    with TemporaryDirectory(prefix="stackopt-ligo-check-") as directory:
        work = Path(directory)
        for index, limits in enumerate(BORE_LIMITS):
            nominal = Decimal(bore["nominal"]["length"]["value"])
            assert all(value["unit"] == "in" for value in options[index]["deviations"].values())
            assert tuple(nominal + Decimal(options[index]["deviations"][side]["value"])
                         for side in ("lower", "upper")) == limits
            corners = [(bore_limit - pin_limit) * INCH
                       for bore_limit, pin_limit in product(limits, PIN_LIMITS)]
            lower, upper = min(corners), max(corners)
            minimum_margin, maximum_margin = lower - minimum, maximum - upper
            row = {
                "option_id": options[index]["id"],
                "lower_mm": lower, "upper_mm": upper,
                "minimum_margin_mm": minimum_margin, "maximum_margin_mm": maximum_margin,
                "meets_study_criterion": minimum_margin >= 0 and maximum_margin >= 0,
                "limiting_side": "minimum" if minimum_margin <= maximum_margin else "maximum",
            }
            expected.append(row)
            variant = deepcopy(case)
            variant["dimensions"][0]["tolerance"]["deviations"] = options[index]["deviations"]
            source = work / f"option-{index}.json"
            source.write_text(json.dumps(variant), encoding="utf-8")
            check_evaluation(run_report("analyze", source, work / "analysis.json")["baseline"], row)

        for source in (HERE / "case.json", args.snapshot):
            analysis = run_report("analyze", source, work / "analysis.json")
            allocation = run_report("allocate", source, work / "allocation.json")
            check_evaluation(analysis["baseline"], expected[0])
            check_evaluation(allocation["baseline"], expected[0])
            assert allocation["search"] == {"status": "complete", "total": 2, "evaluated": 2, "feasible": 1}
            assert [item["index"] for item in allocation["feasible_candidates"]] == [0]
            check_evaluation(allocation["feasible_candidates"][0]["evaluation"], expected[0])
            assert allocation["ranking"] == {
                "status": "unranked", "best_candidate_indices": [], "reason": "no_objective",
            }

    print(json.dumps({"independent_drawing_check": expected,
                      "manual_and_snapshot_cli_match": True}, default=str, indent=2))


if __name__ == "__main__":
    main()
