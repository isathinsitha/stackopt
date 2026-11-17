"""Fixture-only input tools and exhaustive dimensional corner oracle. No StackOpt imports."""

import argparse
import json
from decimal import Context, Decimal, Inexact, localcontext
from itertools import product
from pathlib import Path
from typing import NamedTuple


FIXTURES = Path(__file__).resolve().parents[1] / "examples" / "acceptance-v1"
EXACT = Context(prec=50, traps=[Inexact])


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def quantity(value, unit="mm"):
    return {"value": value, "unit": unit}


def scenario_case(scenario):
    case = load("manual-case.json")
    case["case_id"] += ":" + scenario["id"]
    case["requirement"] = {
        "id": case["requirement"]["id"],
        **{side: quantity(value) for side, value in scenario["limits_mm"].items()},
    }
    mode = scenario.get("objective_variant")
    if mode == "equal_tight_scores":
        case["option_groups"][1]["options"][1]["score"]["value"] = "1"
    elif mode == "omit_objective_and_scores":
        del case["objective"]
        for group in case["option_groups"]:
            for option in group["options"]:
                del option["score"]
    elif mode == "omit_bore_baseline_score":
        del case["option_groups"][0]["options"][0]["score"]
    elif mode is not None:
        raise ValueError(f"Unknown fixture objective variant: {mode}")
    geometry = scenario.get("geometry_variant")
    if geometry == "governing_temperature_shift":
        # Same CTE for both dimensions; tightening the bore changes the sign of
        # the lower clearance, and therefore reverses its temperature slope.
        case["dimensions"][1]["alpha"] = case["dimensions"][0]["alpha"].copy()
        wide_bore = {"lower": quantity("-0.1"), "upper": quantity("0.1")}
        case["dimensions"][0]["tolerance"]["deviations"] = wide_bore
        case["option_groups"][0]["options"][0]["deviations"] = wide_bore
    elif geometry == "minimax_tie":
        case["model"]["operating_min"] = case["model"]["reference"].copy()
        case["model"]["operating_max"] = case["model"]["reference"].copy()
        case["option_groups"].pop()  # Fix the shaft at its baseline offsets.
        case["option_groups"][0]["options"] = [
            {"id": name, "deviations": {"lower": quantity(lower), "upper": quantity(upper)},
             "score": {"value": str(index)}}
            for index, (name, lower, upper) in enumerate((
                ("positive-shift", "0.012", "0.012"),
                ("balanced", "-0.01", "0.01"),
                ("negative-shift", "-0.01", "-0.01"),
            ))
        ]
    elif geometry is not None:
        raise ValueError(f"Unknown fixture geometry variant: {geometry}")
    return case


def diagnostic_inputs(scenario):
    if "record_index" in scenario:
        snapshot = load("cad-shaped-snapshot.json")
        record = snapshot["extraction_records"][scenario["record_index"]]
        record["tolerance"] = scenario["tolerance_evidence"]
        record["diagnostics"] = [scenario["adapter_warning"]]
        return snapshot["case"], snapshot["extraction_records"]

    case = load("manual-case.json")
    # The fixture paths are literal object keys, not a general JSON Pointer implementation.
    replacement = scenario["replace"]
    *parents, leaf = replacement["path"].strip("/").split("/")
    target = case
    for key in parents:
        target = target[key]
    target[leaf] = replacement["value"]
    return case, None


def bore_only_case():
    case = load("manual-case.json")
    case["case_id"] += ":bore-only"
    case["dimensions"][0]["tolerance"]["deviations"] = case["option_groups"][0]["options"][1]["deviations"]
    case["dimensions"][0]["tolerance"]["source_ref"] = "synthetic bore-tight option"
    del case["option_groups"], case["objective"]
    return case


def length_mm(quantity):
    return Decimal(quantity["value"]) * {"mm": Decimal(1), "m": Decimal(1000),
                                        "in": Decimal("25.4")}[quantity["unit"]]


def celsius(quantity):
    return Decimal(quantity["value"]) - {"degC": Decimal(0), "K": Decimal("273.15")}[quantity["unit"]]


def dimensions_from_fixture(case, records=(), choices=()):
    """Read the authored fixture inputs into (physical_id, alpha, lower_mm, upper_mm).

    This is a projection of known valid fixture data, not a validator or resolver.
    Each optional choice is a (callout, deviations) pair from the fixture.
    """
    by_id = {record["logical_id"]: record for record in records}
    result = {}
    with localcontext(EXACT):
        for dim in case["dimensions"]:
            logical_id = dim["logical_id"]
            nominal = dim["nominal"]
            tolerance = dim["tolerance"]
            length = length_mm(nominal["length"] if nominal["kind"] == "manual" else by_id[logical_id]["nominal"])
            deviations = (tolerance["deviations"] if tolerance["kind"] == "manual"
                          else by_id[logical_id]["tolerance"]["deviations"])
            for callout, option_deviations in choices:
                if dim["callout"] == callout:
                    deviations = option_deviations
                    break
            result[logical_id] = (
                dim["physical_id"], Decimal(dim["alpha"]["value"]),
                length + length_mm(deviations["lower"]), length + length_mm(deviations["upper"]),
            )
    return result


class Corner(NamedTuple):
    temperature: Decimal
    value: Decimal
    contributions: tuple[Decimal, ...]  # raw chain order, before any coalescing


def corner_extrema(case, *, records=(), choices=()):
    """Return {temperature: (lowest_corner, highest_corner)} by visiting every corner.

    One drawn length is selected per physical ID, then substituted into each
    original term. This checks repeated aliases without copying coefficient
    coalescing or choosing each term's endpoints by its sign.
    """
    dimensions = dimensions_from_fixture(case, records, choices)
    axes = {}
    for physical_id, alpha, lower, upper in dimensions.values():
        limits = tuple(dict.fromkeys((lower, upper)))
        if axes.setdefault(physical_id, (alpha, limits)) != (alpha, limits):
            raise ValueError(f"Conflicting fixture definitions for {physical_id}")
    terms = [(dimensions[term["logical_id"]][0], Decimal(term["coefficient"]))
             for term in case["chain"]["terms"]]
    model = case["model"]
    output = {}
    with localcontext(EXACT):
        reference = celsius(model["reference"])
        for temperature in sorted({celsius(model["operating_min"]), celsius(model["operating_max"])}):
            corners = []
            for lengths in product(*(limits for _, limits in axes.values())):
                actual = {
                    physical_id: drawn + drawn * alpha * (temperature - reference)
                    for (physical_id, (alpha, _)), drawn in zip(axes.items(), lengths, strict=True)
                }
                contributions = tuple(coef * actual[physical_id] for physical_id, coef in terms)
                corners.append(Corner(temperature, sum(contributions, Decimal(0)), contributions))
            output[temperature] = (min(corners, key=lambda c: c.value), max(corners, key=lambda c: c.value))
    return output


def write_inputs(directory):
    """Materialize runnable CLI inputs and adapter payloads without overwriting files."""
    directory.mkdir(parents=True, exist_ok=False)

    def write(name, document):
        (directory / (name + ".json")).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    snapshot = load("cad-shaped-snapshot.json")
    for name in ("manual-case", "cad-shaped-snapshot", "shared-callout-case"):
        write(name, load(name + ".json"))
    write("bore-only-analysis", bore_only_case())
    write("cad-bound-case", snapshot["case"])
    write("cad-extraction-records", snapshot["extraction_records"])
    for scenario in load("report-cases.json"):
        write(scenario["id"], scenario_case(scenario))
    for scenario in load("diagnostic-cases.json"):
        case, records = diagnostic_inputs(scenario)
        write(scenario["id"], case)
        if records is not None:
            write(scenario["id"] + "-records", records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True, help="New directory for runnable fixtures")
    write_inputs(parser.parse_args().export)
