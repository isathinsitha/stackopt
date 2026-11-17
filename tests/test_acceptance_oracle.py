"""Check the hand-authored goldens against exhaustive geometry, without the engine."""

import unittest
from decimal import Decimal as D
from itertools import product

from acceptance_oracle import (
    bore_only_case,
    celsius,
    corner_extrema,
    dimensions_from_fixture,
    length_mm,
    load,
    scenario_case,
)


def assignments(case):
    groups = case["option_groups"]
    for options in product(*(group["options"] for group in groups)):
        yield options, tuple((group["callout"], option["deviations"])
                             for group, option in zip(groups, options, strict=True))


def envelope(at_temperature):
    # corner_extrema inserts temperatures in ascending order, so ties pick the cold endpoint.
    return (min((row[0] for row in at_temperature.values()), key=lambda bound: bound.value),
            max((row[1] for row in at_temperature.values()), key=lambda bound: bound.value))


def margins(requirement, bounds):
    low, high = bounds
    return {side: (bound.value - length_mm(requirement[side])) * sign
            for side, bound, sign in (("minimum", low, 1), ("maximum", high, -1))
            if side in requirement}


def decimals(mapping):
    return {key: D(value) for key, value in mapping.items()}


class AcceptanceOracleTests(unittest.TestCase):
    def test_hand_bounds_and_signed_terms_at_every_candidate(self):
        case = load("manual-case.json")
        reference = load("reference.json")
        self.assertEqual(case["requirement"]["id"], reference["requirement_id"])
        cold, hot = map(D, reference["temperature_endpoints_degC"])
        expected_rows = reference["candidates"]
        self.assertEqual(len(list(assignments(case))), len(expected_rows))
        for index, ((options, choices), row) in enumerate(zip(assignments(case), expected_rows, strict=True)):
            with self.subTest(index=index):
                self.assertEqual(row["index"], index)
                self.assertEqual([option["id"] for option in options], row["option_ids"])
                self.assertEqual(sum(D(option["score"]["value"]) for option in options), D(row["score"]))
                for dimension, option in zip(dimensions_from_fixture(case, choices=choices).values(),
                                             options, strict=True):
                    drawing_limits = reference["reference_drawing_limits_mm"][option["id"]]
                    self.assertEqual(dimension[2:], tuple(map(D, drawing_limits)))
                endpoints = corner_extrema(case, choices=choices)
                for temperature, key in ((cold, "cold_bounds_mm"), (hot, "hot_bounds_mm")):
                    self.assertEqual(tuple(bound.value for bound in endpoints[temperature]), tuple(map(D, row[key])))
                lower, upper = envelope(endpoints)
                self.assertEqual((lower.temperature, upper.temperature), (cold, hot))
                self.assertEqual(lower.contributions, tuple(map(D, row["lower_signed_terms_mm"])))
                self.assertEqual(upper.contributions, tuple(map(D, row["upper_signed_terms_mm"])))

    def test_baseline_and_standalone_bore_change_match_the_hand_solution(self):
        case = load("manual-case.json")
        fixed = bore_only_case()
        choice = list(assignments(case))[2][1]
        self.assertEqual(corner_extrema(fixed), corner_extrema(case, choices=choice))
        reference = load("reference.json")
        checked = {}
        for authored, key in ((case, "baseline"), (fixed, "bore_only")):
            bounds = envelope(corner_extrema(authored))
            self.assertEqual(tuple(bound.value for bound in bounds),
                             tuple(map(D, reference[key]["envelope_mm"])))
            checked[key] = margins(authored["requirement"], bounds)
            self.assertEqual(checked[key], decimals(reference[key]["margins_mm"]))
            self.assertEqual(min(checked[key], key=checked[key].get), reference[key]["limiting_side"])
        delta = {side: value - checked["baseline"][side] for side, value in checked["bore_only"].items()}
        self.assertEqual(delta, decimals(reference["bore_only"]["margin_delta_mm"]))
        self.assertEqual(delta["maximum"] * 1000, D("10.0092"))
        self.assertEqual(delta["maximum"] * 1000, D(reference["bore_only"]["upper_margin_delta_um"]))

    def test_cad_fixture_numeric_parity_and_selected_tolerance_evidence(self):
        manual = load("manual-case.json")
        snapshot = load("cad-shaped-snapshot.json")
        case, records, problem = (snapshot[key] for key in ("case", "extraction_records", "problem"))
        self.assertEqual(corner_extrema(manual), corner_extrema(case, records=records))
        self.assertEqual(manual["chain"], case["chain"])
        self.assertEqual(manual["requirement"], case["requirement"])
        self.assertEqual(manual["model"], case["model"])
        self.assertEqual(case["chain"], problem["chain"])
        self.assertEqual(manual["objective"], problem["objective"])
        self.assertEqual(problem["requirement"], {"id": case["requirement"]["id"],
                         **{side: str(length_mm(case["requirement"][side])) for side in ("minimum", "maximum")}})
        for key in ("reference", "operating_min", "operating_max"):
            self.assertEqual(celsius(case["model"][key]), D(problem["model"][key]))
        dimensions = dimensions_from_fixture(manual)
        for authored, resolved, record in zip(case["dimensions"], problem["dimensions"], records, strict=True):
            target, source = authored["nominal"]["target"], record["source"]
            logical_id = authored["logical_id"]
            self.assertEqual(record["logical_id"], logical_id)
            self.assertEqual({key: source[key] for key in target}, target)
            self.assertEqual(source["application_version"], "synthetic-fixture")
            physical_id, alpha, lower, upper = dimensions[logical_id]
            self.assertEqual(resolved["logical_id"], logical_id)
            self.assertEqual(resolved["physical_id"], physical_id)
            self.assertEqual(resolved["callout"], authored["callout"])
            self.assertEqual(D(resolved["alpha"]), alpha)
            self.assertEqual(D(resolved["nominal"]), length_mm(record["nominal"]))
            drawing = resolved["drawing_limits"]
            self.assertEqual((D(drawing["lower"]), D(drawing["upper"])), (lower, upper))
            self.assertEqual((D(drawing["lower"]) - D(resolved["nominal"]),
                              D(drawing["upper"]) - D(resolved["nominal"])),
                             (D(drawing["deviations"]["lower"]), D(drawing["deviations"]["upper"])))
            self.assertEqual(resolved["tolerance_source"], authored["tolerance"]["kind"])
        for authored, resolved in zip(manual["option_groups"], problem["option_groups"], strict=True):
            self.assertEqual(authored["callout"], resolved["callout"])
            for option, normalized in zip(authored["options"], resolved["options"], strict=True):
                self.assertEqual((option["id"], option["score"]), (normalized["id"], normalized["score"]))
                self.assertEqual({side: length_mm(value) for side, value in option["deviations"].items()},
                                 decimals(normalized["deviations"]))
        self.assertNotEqual(length_mm(records[0]["tolerance"]["deviations"]["upper"]),
                            D(problem["dimensions"][0]["drawing_limits"]["deviations"]["upper"]))
        warning, = snapshot["diagnostics"]
        self.assertEqual((warning["code"], warning["severity"], warning["logical_id"], warning["field"]),
                         ("cad.tolerance_discrepancy", "warning", "bore", "/dimensions/0/tolerance"))

    def test_golden_report_projections_follow_from_the_tested_prefix(self):
        for scenario in load("report-cases.json"):
            with self.subTest(scenario=scenario["id"]):
                self.check_report_case(scenario)

    def check_report_case(self, scenario):
        case = scenario_case(scenario)
        requirement, expected = case["requirement"], scenario["expected"]
        control = scenario.get("search_control", {})
        stop = control.get("interrupt_after", control.get("budget", {}).get("max_evaluations"))
        baseline_endpoints = corner_extrema(case)
        baseline_bounds = envelope(baseline_endpoints)
        baseline_margins = margins(requirement, baseline_bounds)
        self.assertEqual(baseline_margins, decimals(expected["baseline_margins_mm"]))
        all_assignments = list(assignments(case))
        checked = [(options, corner_extrema(case, choices=choices))
                   for options, choices in all_assignments[:stop]]
        bounds = [envelope(endpoints) for _, endpoints in checked]
        values = [margins(requirement, pair) for pair in bounds]
        feasible = [index for index, declared in enumerate(values) if min(declared.values()) >= 0]
        self.assertEqual(feasible, expected["feasible_indices"])
        search = expected["search"]
        self.assertEqual((len(all_assignments), len(checked), len(feasible)),
                         (search["total"], search["evaluated"], search["feasible"]))
        if not checked:
            status, exit_status = "zero_tested", 7
        elif stop is not None:
            status, exit_status = "incomplete", 7
        elif feasible:
            status, exit_status = "complete", 0
        else:
            status, exit_status = "infeasible", 6
        self.assertEqual((search["status"], expected["exit_status"]), (status, exit_status))
        if stop is not None:
            self.assertLess(len(checked), len(all_assignments))
            self.assertEqual(search["stop_reason"], "evaluation_limit" if "budget" in control else "interrupted")
            self.assertEqual(search.get("budget"), control.get("budget"))
            self.assertEqual(expected["diagnostic"], {"code": "search.incomplete", "severity": "warning"})
        else:
            self.assertNotIn("diagnostic", expected)

        ranking = expected["ranking"]
        fully_scored = all("score" in option for options, _ in all_assignments for option in options)
        if "objective" not in case or not fully_scored:
            self.assertEqual(ranking, {"status": "unranked", "best_candidate_indices": [],
                             "reason": "missing_scores" if "objective" in case else "no_objective"})
            best = []
        else:
            scores = {i: sum(D(option["score"]["value"]) for option in checked[i][0]) for i in feasible}
            best = [i for i in feasible if scores[i] == min(scores.values())]
            self.assertEqual(ranking, {"status": "provisional" if stop is not None else "complete",
                                       "best_candidate_indices": best})

        if checked and not feasible:
            worst = [max(-margin for margin in declared.values()) for declared in values]
            index = worst.index(min(worst))
            role = "closest_so_far" if stop is not None else "closest_tested"
            self.assertEqual(expected["closest"], {"candidate_index": index, "qualification": role,
                                                    "maximum_violation_mm": format(worst[index].normalize(), "f")})
        else:
            self.assertNotIn("closest", expected)
            if not best:
                self.assertNotIn("comparison", expected)
                return
            index, role = best[0], "provisional_best" if stop is not None else "selected"
        comparison = expected["comparison"]
        self.assertEqual((comparison["candidate_index"], comparison["role"]), (index, role))
        self.assertEqual(decimals(comparison["candidate_margins_mm"]), values[index])
        self.assertEqual(decimals(comparison["margin_delta_mm"]),
                         {side: value - baseline_margins[side] for side, value in values[index].items()})
        for side, record in comparison.get("attribution", {}).items():
            position, sign = (0, 1) if side == "minimum" else (1, -1)
            before, after = baseline_bounds[position], bounds[index][position]
            same = checked[index][1][before.temperature][position]
            self.assertEqual(decimals(record), {
                "baseline_temperature": before.temperature, "candidate_temperature": after.temperature,
                "same_temperature_delta": sign * (same.value - before.value),
                "governing_temperature_delta": sign * (after.value - same.value),
            })

    def test_shared_callout_changes_both_occurrences_without_correlating_them(self):
        case = load("shared-callout-case.json")
        _, choices = next(assignments(case))
        for selection, expected in (((), ("-3.575", "-2.975")), (choices, ("-3.475", "-3.075"))):
            lower, upper = envelope(corner_extrema(case, choices=selection))
            self.assertEqual((lower.temperature, upper.temperature), (D("-20"), D("-20")))
            self.assertEqual((lower.value, upper.value), tuple(map(D, expected)))
        self.assertEqual(margins(case["requirement"], (lower, upper)), {"minimum": D(0), "maximum": D(0)})


if __name__ == "__main__":
    unittest.main()
