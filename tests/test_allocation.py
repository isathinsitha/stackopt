"""Check exact allocation evidence against independent v1 fixture expectations."""

import unittest
from copy import deepcopy
from fractions import Fraction
from unittest.mock import patch

from acceptance_oracle import FIXTURES, load, quantity, scenario_case
from stackopt.allocation import allocate, apply_assignment
from stackopt.analysis import evaluate, evaluate_at_temperature
from stackopt.case import resolve_case
from stackopt.diagnostics import ContractError, ExitStatus
from stackopt.snapshot import load_problem


def _manual_problem():
    return load_problem(FIXTURES / "manual-case.json").problem


def _margins(expected):
    return {side: Fraction(value) for side, value in expected.items()}


class AllocationTests(unittest.TestCase):
    def test_manual_and_frozen_cad_reference(self):
        reference = load("reference.json")
        for fixture in ("manual-case.json", "cad-shaped-snapshot.json"):
            with self.subTest(fixture=fixture):
                problem = load_problem(FIXTURES / fixture).problem
                before = deepcopy(problem)
                run = allocate(problem)
                self.assertEqual(problem, before)
                self.assertEqual(run["baseline"], evaluate(problem))
                self.assertEqual(run["ranking"]["objective"], problem["objective"])
                self.assertEqual(run["ranking"]["best_candidate_indices"], [2])
                self.assertEqual([item["index"] for item in run["feasible_candidates"]], [1, 2, 3])
                for candidate in run["feasible_candidates"]:
                    row = reference["candidates"][candidate["index"]]
                    self.assertEqual(candidate["total_score"], Fraction(row["score"]))
                    self.assertEqual([item["option_id"] for item in candidate["assignment"]], row["option_ids"])
                    active = apply_assignment(problem, candidate["assignment"])
                    evaluation = candidate["evaluation"]
                    self.assertEqual(evaluation, evaluate(active))
                    for temperature, endpoint in ((-20, "cold"), (60, "hot")):
                        bounds = evaluate_at_temperature(active, temperature)
                        self.assertEqual([bound["value"] for bound in bounds],
                                         list(map(Fraction, row[f"{endpoint}_bounds_mm"])))
                    for side in ("lower", "upper"):
                        contributions = [term["contribution"] for term in evaluation[f"{side}_bound"]["terms"]]
                        self.assertEqual(contributions, list(map(Fraction, row[f"{side}_signed_terms_mm"])))

    def test_scenarios_match_search_ranking_and_comparison_fixtures(self):
        for scenario in load("report-cases.json"):
            with self.subTest(scenario=scenario["id"]):
                problem = resolve_case(scenario_case(scenario)).problem
                control = scenario.get("search_control", {})
                kwargs = {}
                if "budget" in control:
                    kwargs["budget"] = control["budget"]
                if "interrupt_after" in control:
                    polls = iter([False] * control["interrupt_after"] + [True])
                    kwargs["should_stop"] = lambda: next(polls)
                run = allocate(problem, **kwargs)
                expected = scenario["expected"]
                self.assertEqual(run["search"], expected["search"])
                self.assertEqual(run["baseline"]["margins"], _margins(expected["baseline_margins_mm"]))
                self.assertEqual(run["ranking"], {
                    **expected["ranking"], **({"objective": problem["objective"]} if "objective" in problem else {}),
                })
                feasible = {item["index"]: item for item in run["feasible_candidates"]}
                self.assertEqual(list(feasible), expected["feasible_indices"])
                if "diagnostic" in expected:
                    warning, = run["diagnostics"]
                    self.assertEqual({key: warning[key] for key in ("code", "severity")}, expected["diagnostic"])
                else:
                    self.assertEqual(run["diagnostics"], [])

                comparison = None
                if "closest" in expected:
                    closest = run["closest"]
                    expected_closest = expected["closest"]
                    self.assertEqual(closest["qualification"], expected_closest["qualification"])
                    self.assertEqual(closest["maximum_violation"], Fraction(expected_closest["maximum_violation_mm"]))
                    comparison = closest["candidate"]
                    self.assertFalse(comparison["evaluation"]["meets_requirement"])
                    self.assertEqual(comparison["index"], expected_closest["candidate_index"])
                else:
                    self.assertNotIn("closest", run)
                    best = run["ranking"]["best_candidate_indices"]
                    if best:
                        comparison = feasible[best[0]]

                if "comparison" in expected:
                    self.assertIsNotNone(comparison)
                    self.assertEqual(comparison["index"], expected["comparison"]["candidate_index"])
                    evaluation = comparison["evaluation"]
                    self.assertEqual(evaluation["margins"], _margins(expected["comparison"]["candidate_margins_mm"]))
                    self.assertEqual(
                        {side: value - run["baseline"]["margins"][side] for side, value in evaluation["margins"].items()},
                        _margins(expected["comparison"]["margin_delta_mm"]),
                    )
                    self.assertEqual(evaluation, evaluate(apply_assignment(problem, comparison["assignment"])))
                else:
                    self.assertIsNone(comparison)
                if run["ranking"]["status"] == "unranked":
                    for candidate in feasible.values():
                        self.assertNotIn("total_score", candidate)
                    if scenario["id"] == "missing-score":
                        self.assertEqual([item["score"]["value"] for item in feasible[3]["assignment"]], [1, 3])

    def test_shared_callout_has_one_score_and_independent_physical_occurrences(self):
        case = load("shared-callout-case.json")
        case["objective"] = load("manual-case.json")["objective"]
        score = {"value": "2.25", "source_ref": "synthetic shared-option evidence"}
        case["option_groups"][0]["options"][0]["score"] = score
        problem = resolve_case(case).problem
        run = allocate(problem)
        candidate, = run["feasible_candidates"]
        selection, = candidate["assignment"]
        self.assertEqual(selection["score"], {**score, "value": Fraction("2.25")})
        self.assertEqual(candidate["total_score"], Fraction("2.25"))
        evaluation = candidate["evaluation"]
        self.assertEqual(evaluation["margins"], {"minimum": 0, "maximum": 0})
        self.assertEqual([row["physical_id"] for row in evaluation["drawing_limits"]], ["a-1", "a-2", "b-1", "c-1"])
        self.assertEqual([row["tolerance_source"] for row in evaluation["drawing_limits"]],
                         ["option", "option", "manual", "manual"])
        self.assertEqual([term["coefficient"] for term in evaluation["upper_bound"]["terms"]], [1, -1, -1, Fraction(1, 2)])
        active = apply_assignment(problem, candidate["assignment"])
        self.assertEqual([item["drawing_limits"]["upper"] for item in active["dimensions"][:3]],
                         [Fraction("10.1")] * 3)

    def test_assignment_matches_full_callout_key_and_uses_each_nominal(self):
        case = load("shared-callout-case.json")
        callout = {**case["option_groups"][0]["callout"], "revision": "R2", "configuration": "standard"}
        case["option_groups"][0]["callout"] = callout
        for dimension in case["dimensions"][:3]:
            dimension["callout"] = callout
        case["dimensions"][2]["nominal"]["length"] = quantity("11")
        fixed = case["dimensions"][3:]
        fixed[0]["callout"] = {**callout, "revision": "R1"}
        fixed[1]["callout"] = {**callout, "configuration": "alternate"}
        for identifier, other in (
            ("other-dimension", {**callout, "dimension_id": "width"}),
            ("unqualified", {key: callout[key] for key in ("document_id", "dimension_id")}),
        ):
            case["dimensions"].append({**fixed[1], "logical_id": identifier, "physical_id": identifier, "callout": other})
            case["chain"]["terms"].append({"logical_id": identifier, "coefficient": "0"})
        case["requirement"] = {"id": "synthetic-limit", "maximum": quantity("0")}
        problem = resolve_case(case).problem
        candidate, = allocate(problem)["feasible_candidates"]
        active = apply_assignment(problem, candidate["assignment"])
        self.assertEqual([row["drawing_limits"]["upper"] for row in active["dimensions"][:3]],
                         list(map(Fraction, ("10.1", "10.1", "11.1"))))
        self.assertEqual(active["dimensions"][3:], problem["dimensions"][3:])
        self.assertEqual(evaluate(active), candidate["evaluation"])

    def test_no_groups_evaluates_empty_assignment_and_checks_baseline_independently(self):
        problem = _manual_problem()
        problem["option_groups"] = []
        with patch("stackopt.allocation.evaluate", wraps=evaluate) as evaluator:
            run = allocate(problem)
        self.assertEqual(evaluator.call_count, 2)
        self.assertEqual(run["search"], {"status": "infeasible", "evaluated": 1, "total": 1, "feasible": 0})
        candidate = run["closest"]["candidate"]
        self.assertEqual(candidate, {"index": 0, "assignment": [], "evaluation": run["baseline"]})
        self.assertEqual(run["ranking"], {"status": "unranked", "reason": "no_option_groups",
                                         "objective": problem["objective"], "best_candidate_indices": []})
        self.assertEqual(apply_assignment(problem, candidate["assignment"]), problem)

        del problem["objective"]
        problem["requirement"] = {"id": "loose-limit", "minimum": Fraction("0.04")}
        run = allocate(problem)
        self.assertEqual(run["feasible_candidates"], [{"index": 0, "assignment": [], "evaluation": run["baseline"]}])
        self.assertEqual(run["ranking"]["reason"], "no_objective")
        self.assertNotIn("closest", run)

    def test_passing_baseline_is_excluded_when_its_interval_is_undeclared(self):
        case = load("manual-case.json")
        case["requirement"] = {"id": "maximum-gap", "maximum": quantity("0.16")}
        bore, _ = case["option_groups"]
        bore["options"] = [{
            "id": "wide-only", "deviations": {"lower": quantity("-0.05"), "upper": quantity("0.05")},
            "score": {"value": "0"},
        }]
        case["option_groups"] = [bore]
        problem = resolve_case(case).problem
        run = allocate(problem)
        self.assertTrue(run["baseline"]["meets_requirement"])
        self.assertEqual(run["search"], {"status": "infeasible", "total": 1, "evaluated": 1, "feasible": 0})
        closest = run["closest"]
        self.assertEqual(closest["maximum_violation"], Fraction("0.02395"))
        self.assertEqual(closest["candidate"]["evaluation"]["margins"], {"maximum": Fraction("-0.02395")})

    def test_unranked_prefix_keeps_a_pass_even_after_a_later_failure(self):
        scenario = {"id": "unranked-prefix", "geometry_variant": "minimax_tie", "limits_mm": {"minimum": "0.07"}}
        case = scenario_case(scenario)
        del case["objective"]
        for option in case["option_groups"][0]["options"]:
            del option["score"]
        problem = resolve_case(case).problem
        run = allocate(problem, budget={"max_evaluations": 2})
        self.assertEqual(run["search"]["status"], "incomplete")
        self.assertEqual(run["search"]["feasible"], 1)
        candidate, = run["feasible_candidates"]
        self.assertEqual(candidate["index"], 0)
        self.assertEqual(run["ranking"], {"status": "unranked", "reason": "no_objective", "best_candidate_indices": []})
        self.assertNotIn("closest", run)

    def test_assignment_requires_known_options_for_all_groups(self):
        problem = _manual_problem()
        a, b = allocate(problem)["feasible_candidates"][0]["assignment"]
        for assignment in ([a], [a, b, a], [a, {**b, "option_id": "other-option"}]):
            with self.subTest(assignment=assignment), self.assertRaises(ValueError):
                apply_assignment(problem, assignment)

    def test_zero_count_budget_and_budget_equal_to_total(self):
        problem = _manual_problem()
        with patch("stackopt.allocation.evaluate", wraps=evaluate) as evaluator:
            stopped = allocate(problem, budget={"max_evaluations": 0})
        self.assertEqual(evaluator.call_count, 1)
        self.assertEqual(stopped["search"], {"status": "zero_tested", "total": 4, "evaluated": 0, "feasible": 0,
                                             "budget": {"max_evaluations": 0}, "stop_reason": "evaluation_limit"})
        self.assertNotIn("closest", stopped)
        complete = allocate(problem, budget={"max_evaluations": 4})
        self.assertEqual(complete["search"], {"status": "complete", "total": 4, "evaluated": 4, "feasible": 3,
                                              "budget": {"max_evaluations": 4}})
        self.assertEqual(complete["diagnostics"], [])

    def test_time_budget_checks_before_evaluating_each_candidate(self):
        problem = _manual_problem()
        with patch("stackopt.allocation.monotonic_ns", side_effect=[0, 1, 500_000_000]):
            run = allocate(problem, budget={"max_seconds": Fraction("0.5")})
        self.assertEqual(run["search"], {"status": "incomplete", "total": 4, "evaluated": 1, "feasible": 0,
                                        "budget": {"max_seconds": Fraction("0.5")}, "stop_reason": "time_limit"})
        self.assertEqual(run["closest"]["qualification"], "closest_so_far")
        self.assertEqual(run["closest"]["candidate"]["index"], 0)

        with patch("stackopt.allocation.monotonic_ns", return_value=0):
            run = allocate(problem, budget={"max_seconds": Fraction(0)})
        self.assertEqual(run["search"]["status"], "zero_tested")
        self.assertEqual(run["search"]["stop_reason"], "time_limit")
        self.assertNotIn("closest", run)

    def test_invalid_budget_is_rejected_before_evaluation(self):
        problem = _manual_problem()
        invalid = ({"max_evaluations": -1}, {"max_evaluations": True}, {"max_seconds": Fraction(-1)},
                   {"max_seconds": Fraction(1, 3)}, {"max_seconds": 0.5}, {"max_seconds": True}, {"max_count": 5})
        with patch("stackopt.allocation.evaluate") as evaluator:
            for budget in invalid:
                with self.subTest(budget=budget), self.assertRaises(ValueError):
                    allocate(problem, budget=budget)
        evaluator.assert_not_called()

    def test_keyboard_interrupt_during_candidate_leaves_completed_prefix(self):
        problem = _manual_problem()
        baseline = evaluate(problem)
        with patch("stackopt.allocation.evaluate", side_effect=[baseline, baseline, KeyboardInterrupt]):
            run = allocate(problem)
        self.assertEqual(run["search"]["status"], "incomplete")
        self.assertEqual(run["search"]["stop_reason"], "interrupted")
        self.assertEqual(run["search"]["evaluated"], 1)
        self.assertEqual(run["closest"]["candidate"]["index"], 0)

    def test_evaluator_failures_abort_instead_of_returning_a_search_status(self):
        problem = _manual_problem()
        unexpected = RuntimeError("injected evaluator failure")
        with patch("stackopt.allocation.evaluate", side_effect=[evaluate(problem), unexpected]) as evaluator:
            with self.assertRaises(ContractError) as caught:
                allocate(problem)
        self.assertEqual(evaluator.call_count, 2)
        self.assertEqual(caught.exception.exit_status, ExitStatus.EXECUTION_FAILURE)
        self.assertEqual(caught.exception.diagnostic["code"], "internal.failure")
        self.assertIs(caught.exception.__cause__, unexpected)
        with patch("stackopt.allocation.evaluate", side_effect=caught.exception):
            with self.assertRaises(ContractError) as propagated:
                allocate(problem)
        self.assertIs(propagated.exception, caught.exception)

    def test_resolver_rejects_joint_scope(self):
        case = load("manual-case.json")
        case["scope"] = "joint"
        with self.assertRaises(ContractError) as caught:
            resolve_case(case)
        self.assertEqual(caught.exception.exit_status, ExitStatus.INVALID_INPUT)
        self.assertEqual(caught.exception.diagnostic["field"], "/scope")


if __name__ == "__main__":
    unittest.main()
