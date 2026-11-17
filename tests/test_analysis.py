"""Compare the v1 evaluator with hand results and independent dimensional corners."""

import unittest
from copy import deepcopy
from fractions import Fraction

from acceptance_oracle import FIXTURES, bore_only_case, corner_extrema, load, quantity, scenario_case
from stackopt.analysis import evaluate, evaluate_at_temperature
from stackopt.case import resolve_case
from stackopt.diagnostics import ContractError, ExitStatus
from stackopt.snapshot import load_problem


def _bounds(evaluation):
    return evaluation["lower_bound"], evaluation["upper_bound"]


def _values(bounds):
    return tuple(bound["value"] for bound in bounds)


def _with_choices(problem, choices):
    """Apply specific fixture choices to a candidate copy without the allocator."""
    candidate = deepcopy(problem)
    for dimension in candidate["dimensions"]:
        for callout, deviations in choices:
            if dimension["callout"] == callout:
                offsets = {side: Fraction(value["value"]) for side, value in deviations.items()}
                nominal = dimension["nominal"]
                dimension["drawing_limits"] = {
                    "deviations": offsets,
                    "lower": nominal + offsets["lower"],
                    "upper": nominal + offsets["upper"],
                }
                dimension["tolerance_source"] = "option"
    return candidate


class AnalysisTests(unittest.TestCase):
    def assertTraceReconstructs(self, trace):
        self.assertIsInstance(trace["value"], Fraction)
        self.assertEqual(trace["value"], sum(term["contribution"] for term in trace["terms"]))
        for term in trace["terms"]:
            self.assertEqual(term["contribution"], term["coefficient"] * term["expanded_length"])

    def assertMatchesCorners(self, problem, corners):
        result = evaluate(problem)
        for temperature, expected in corners.items():
            traces = evaluate_at_temperature(problem, Fraction(temperature))
            self.assertEqual(_values(traces), tuple(corner.value for corner in expected))
            for trace in traces:
                self.assertEqual(trace["temperature"], temperature)
                self.assertTraceReconstructs(trace)
        lower = min((pair[0] for pair in corners.values()), key=lambda corner: corner.value)
        upper = max((pair[1] for pair in corners.values()), key=lambda corner: corner.value)
        for trace, expected in zip(_bounds(result), (lower, upper), strict=True):
            self.assertEqual((trace["value"], trace["temperature"]), (expected.value, expected.temperature))
            self.assertTraceReconstructs(trace)

    def test_hand_baseline_manual_and_frozen_cad_shaped_replay(self):
        reference = load("reference.json")
        results = []
        for filename in ("manual-case.json", "cad-shaped-snapshot.json"):
            with self.subTest(filename=filename):
                problem = load_problem(FIXTURES / filename).problem
                before = deepcopy(problem)
                result = evaluate(problem)
                results.append(result)
                self.assertEqual(problem, before)
                self.assertEqual(_values(_bounds(result)), tuple(map(Fraction, reference["baseline"]["envelope_mm"])))
                self.assertEqual(result["margins"], {"minimum": Fraction("-0.008857"),
                                                     "maximum": Fraction("-0.008927")})
                self.assertEqual(result["limiting_side"], "maximum")
                self.assertFalse(result["meets_requirement"])
                for trace, labels, temperature, field in (
                    (result["lower_bound"], ("lower", "upper"), -20, "lower_signed_terms_mm"),
                    (result["upper_bound"], ("upper", "lower"), 60, "upper_signed_terms_mm"),
                ):
                    self.assertEqual(trace["temperature"], temperature)
                    for index, (term, label) in enumerate(zip(trace["terms"], labels, strict=True)):
                        dimension = problem["dimensions"][index]
                        coefficient = (1, -1)[index]
                        expected = Fraction(reference["candidates"][0][field][index])
                        self.assertEqual(term, {"physical_id": dimension["physical_id"],
                                                "callout": dimension["callout"],
                                                "coefficient": coefficient, "drawing_limit": label,
                                                "expanded_length": expected / coefficient,
                                                "contribution": expected})
                    self.assertTraceReconstructs(trace)
        manual, replay = results
        self.assertEqual(_bounds(manual), _bounds(replay))
        self.assertEqual([row["tolerance_source"] for row in manual["drawing_limits"]], ["manual", "manual"])
        self.assertEqual([row["tolerance_source"] for row in replay["drawing_limits"]], ["manual", "cad"])

    def test_all_hand_fixture_choices_match_corners(self):
        case = load("manual-case.json")
        problem = resolve_case(case).problem
        reference = load("reference.json")
        for row in reference["candidates"]:
            with self.subTest(option_ids=row["option_ids"]):
                choices = []
                for group, option_id in zip(case["option_groups"], row["option_ids"], strict=True):
                    option = next(option for option in group["options"] if option["id"] == option_id)
                    choices.append((group["callout"], option["deviations"]))
                candidate = _with_choices(problem, choices)
                self.assertMatchesCorners(candidate, corner_extrema(case, choices=choices))
                for temperature, expected in ((-20, "cold_bounds_mm"), (60, "hot_bounds_mm")):
                    self.assertEqual(_values(evaluate_at_temperature(candidate, temperature)),
                                     tuple(map(Fraction, row[expected])))
                if row["index"] == 2:
                    standalone = evaluate(resolve_case(bore_only_case()).problem)
                    result = evaluate(candidate)
                    self.assertEqual(_bounds(standalone), _bounds(result))
                    self.assertEqual(standalone["margins"], result["margins"])
                    self.assertTrue(result["meets_requirement"])
                    delta = result["margins"]["maximum"] - evaluate(problem)["margins"]["maximum"]
                    self.assertEqual(delta * 1000, Fraction("10.0092"))

    def test_shared_callout_keeps_occurrences_independent_and_passes_exact_equality(self):
        case = load("shared-callout-case.json")
        case["dimensions"].reverse()
        problem = resolve_case(case).problem
        group, = case["option_groups"]
        option, = group["options"]
        choices = [(group["callout"], option["deviations"])]
        candidate = _with_choices(problem, choices)

        for current, selection, expected in (
            (problem, (), ("-3.575", "-2.975")), (candidate, choices, ("-3.475", "-3.075")),
        ):
            self.assertMatchesCorners(current, corner_extrema(case, choices=selection))
            result = evaluate(current)
            self.assertEqual(_values(_bounds(result)), tuple(map(Fraction, expected)))
            expected_ids = ["a-1", "a-2", "b-1", "c-1"]
            self.assertEqual([row["physical_id"] for row in result["drawing_limits"]], expected_ids)
            for trace in _bounds(result):
                self.assertEqual(trace["temperature"], -20)
                self.assertEqual([term["physical_id"] for term in trace["terms"]], expected_ids)
                self.assertEqual([term["coefficient"] for term in trace["terms"]], [1, -1, -1, Fraction("0.5")])
                self.assertEqual(trace["terms"][-1]["expanded_length"], Fraction("1.05"))
        self.assertEqual(result["margins"], {"minimum": Fraction(0), "maximum": Fraction(0)})
        self.assertTrue(result["meets_requirement"])
        self.assertEqual(result["limiting_side"], "minimum")
        for row in result["drawing_limits"][:2]:
            self.assertEqual(row["tolerance_source"], "option")
            self.assertEqual(row["limits"], {"lower": Fraction(10), "upper": Fraction("10.1"),
                                             "deviations": {"lower": Fraction(0), "upper": Fraction("0.1")}})

    def test_zero_total_coefficients_produce_empty_traces(self):
        case = load("shared-callout-case.json")
        terms = case["chain"]["terms"]
        terms[0]["coefficient"] = "1"
        case["chain"]["terms"] = [terms[0], terms[1], terms[4]]
        case["requirement"] = {"id": "zero", "minimum": quantity("0"), "maximum": quantity("0")}
        problem = resolve_case(case).problem
        result = evaluate(problem)
        self.assertMatchesCorners(problem, corner_extrema(case))
        for trace in _bounds(result):
            self.assertEqual(trace, {"value": Fraction(0), "temperature": Fraction(-20), "terms": []})
        self.assertEqual([row["physical_id"] for row in result["drawing_limits"]], ["a-1", "b-1"])
        self.assertTrue(result["meets_requirement"])

    def test_one_sided_exact_comparison_without_rounding(self):
        for side, limit in (("minimum", "0.041143000000000000000001"),
                            ("maximum", "0.158926999999999999999999")):
            with self.subTest(side=side):
                case = load("manual-case.json")
                case["requirement"] = {"id": "one-sided", side: quantity(limit)}
                result = evaluate(resolve_case(case).problem)
                self.assertEqual(result["margins"], {side: -Fraction(1, 10**24)})
                self.assertFalse(result["meets_requirement"])
                self.assertEqual(result["limiting_side"], side)
                self.assertEqual(_values(_bounds(result)), (Fraction("0.041143"), Fraction("0.158927")))

    def test_fixed_temperature_and_interior_temperature(self):
        case = load("manual-case.json")
        operating = resolve_case(case).problem
        fixed = scenario_case({"id": "fixed", "limits_mm": {"minimum": "0.05"},
                               "geometry_variant": "minimax_tie"})
        self.assertMatchesCorners(resolve_case(fixed).problem, corner_extrema(fixed))
        measurement = quantity("7.25", "degC")
        case["model"].update(operating_min=measurement, operating_max=measurement)
        fixed = resolve_case(case).problem
        point = Fraction("7.25")
        self.assertMatchesCorners(fixed, corner_extrema(case))
        self.assertEqual(evaluate_at_temperature(operating, point), _bounds(evaluate(fixed)))

    def test_same_temperature_traces_for_a_shift_in_governing_temperature(self):
        scenario = next(row for row in load("report-cases.json") if row["id"] == "governing-temperature-shift")
        case = scenario_case(scenario)
        baseline = resolve_case(case).problem
        group = case["option_groups"][0]
        choices = [(group["callout"], group["options"][1]["deviations"])]
        candidate = _with_choices(baseline, choices)
        self.assertMatchesCorners(baseline, corner_extrema(case))
        self.assertMatchesCorners(candidate, corner_extrema(case, choices=choices))
        baseline_lower, baseline_upper = _bounds(evaluate(baseline))
        candidate_lower, candidate_upper = _bounds(evaluate(candidate))
        self.assertEqual((baseline_lower["temperature"], baseline_upper["temperature"]), (60, 60))
        self.assertEqual((candidate_lower["temperature"], candidate_upper["temperature"]), (-20, 60))
        at_baseline_temperature, _ = evaluate_at_temperature(candidate, baseline_lower["temperature"])
        terms = zip(at_baseline_temperature["terms"], baseline_lower["terms"], strict=True)
        same_temperature = sum(new["contribution"] - old["contribution"] for new, old in terms)
        self.assertEqual(same_temperature, Fraction("0.0850782"))
        self.assertEqual(candidate_lower["value"] - at_baseline_temperature["value"], Fraction("-0.0001104"))

    def test_negative_expansion_can_make_upper_bound_govern_at_the_cold_endpoint(self):
        case = load("manual-case.json")
        case["dimensions"][0]["alpha"]["value"] = "-0.000023"
        problem = resolve_case(case).problem
        self.assertMatchesCorners(problem, corner_extrema(case))
        lower, upper = _bounds(evaluate(problem))
        self.assertEqual((lower["temperature"], upper["temperature"]), (60, -20))

    def test_point_query_rejects_inexact_and_out_of_range_temperatures(self):
        problem = load_problem(FIXTURES / "manual-case.json").problem
        for temperature in (True, 20.0, "20"):
            with self.subTest(temperature=temperature), self.assertRaises(TypeError):
                evaluate_at_temperature(problem, temperature)
        for temperature in (Fraction("-20.01"), 61):
            with self.subTest(temperature=temperature), self.assertRaises(ValueError):
                evaluate_at_temperature(problem, temperature)

    def test_broken_candidate_alias_and_thermal_contract_fail_instead_of_comparing(self):
        problem = load_problem(FIXTURES / "shared-callout-case.json").problem
        problem["dimensions"][1]["drawing_limits"]["upper"] += Fraction("0.01")
        with self.assertRaises(ContractError) as caught:
            evaluate(problem)
        self.assertEqual(caught.exception.diagnostic["code"], "internal.failure")
        self.assertEqual(caught.exception.exit_status, ExitStatus.EXECUTION_FAILURE)

        problem = load_problem(FIXTURES / "manual-case.json").problem
        problem["dimensions"][0]["alpha"] = Fraction("0.025")
        with self.assertRaises(ContractError) as caught:
            evaluate(problem)
        self.assertIn("Nonpositive thermal expansion factor", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
