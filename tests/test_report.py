"""Verify the v1 result document and the report-only decision evidence."""

from copy import deepcopy
from decimal import ROUND_DOWN, localcontext
from fractions import Fraction
import json
import unittest

from acceptance_oracle import FIXTURES, load, quantity, scenario_case
from stackopt.allocation import allocate
from stackopt.analysis import evaluate
from stackopt.case import resolve_case
from stackopt.report import (
    build_allocation_report,
    build_analysis_report,
    build_diagnostic_report,
    render_diagnostics,
    render_json,
    render_terminal,
)
from stackopt.snapshot import AnalysisInput, load_problem


def _source(case):
    resolved = resolve_case(case)
    return AnalysisInput(resolved.problem, case["case_id"], "case", resolved.diagnostics)


def _run_scenario(scenario):
    source = _source(scenario_case(scenario))
    control = scenario.get("search_control", {})
    checks = None
    if "interrupt_after" in control:
        checks = iter([False] * control["interrupt_after"] + [True]).__next__
    return build_allocation_report(source, allocate(source.problem, budget=control.get("budget"), should_stop=checks))


class ReportTests(unittest.TestCase):
    def test_json_report_projects_every_acceptance_scenario(self):
        reference = load("reference.json")
        for scenario in load("report-cases.json"):
            with self.subTest(scenario=scenario["id"]):
                report = json.loads(render_json(_run_scenario(scenario)))
                expected = scenario["expected"]
                self.assertEqual((report["kind"], report["schema_version"], report["scope"]),
                                 ("allocation_result", 1, "single_chain"))
                self.assertEqual(report["requirement"], {"id": reference["requirement_id"], **scenario["limits_mm"]})
                self.assertEqual(report["search"], expected["search"])
                self.assertEqual(report["baseline"]["margins"], expected["baseline_margins_mm"])
                self.assertEqual(report["baseline"]["meets_requirement"],
                                 all(Fraction(value) >= 0 for value in expected["baseline_margins_mm"].values()))
                self.assertEqual({field: report["ranking"][field] for field in expected["ranking"]}, expected["ranking"])
                feasible = {item["index"]: item for item in report["feasible_candidates"]}
                self.assertEqual(list(feasible), expected["feasible_indices"])
                if "diagnostic" in expected:
                    warning, = report["diagnostics"]
                    self.assertEqual({key: warning[key] for key in ("code", "severity")}, expected["diagnostic"])
                else:
                    self.assertEqual(report["diagnostics"], [])

                if "closest" in expected:
                    closest = report["closest"]
                    self.assertEqual({
                        "candidate_index": closest["candidate"]["index"], "qualification": closest["qualification"],
                        "maximum_violation_mm": closest["maximum_violation"],
                    }, expected["closest"])
                    candidate = closest["candidate"]
                    self.assertFalse(candidate["evaluation"]["meets_requirement"])
                else:
                    self.assertNotIn("closest", report)
                    best = expected["ranking"]["best_candidate_indices"]
                    candidate = feasible[best[0]] if best else None

                is_reference_geometry = "geometry_variant" not in scenario
                if is_reference_geometry:
                    self.assert_reference_evaluation(report["baseline"], reference, 0)
                    for index, choice in feasible.items():
                        self.assert_reference_evaluation(choice["evaluation"], reference, index)
                if "comparison" not in expected:
                    self.assertNotIn("explanation", report)
                    continue

                comparison = expected["comparison"]
                explanation = report["explanation"]
                self.assertEqual(explanation["candidate_index"], comparison["candidate_index"])
                self.assertEqual(explanation["role"], comparison["role"])
                self.assertEqual(candidate["evaluation"]["margins"], comparison["candidate_margins_mm"])
                self.assertEqual(set(explanation["margins"]), set(scenario["limits_mm"]))
                if is_reference_geometry:
                    self.assert_reference_evaluation(candidate["evaluation"], reference, candidate["index"])
                    expected_changes = [option for option in reference["candidates"][candidate["index"]]["option_ids"]
                                        if option.endswith("-tight")]
                    self.assertEqual([item["option_id"] for item in explanation["callout_changes"]], expected_changes)

                for side, change in explanation["margins"].items():
                    self.assertEqual(change["baseline_margin"], expected["baseline_margins_mm"][side])
                    self.assertEqual(change["candidate_margin"], comparison["candidate_margins_mm"][side])
                    self.assertEqual(change["margin_delta"], comparison["margin_delta_mm"][side])
                    attribution = comparison.get("attribution", {}).get(side, {
                        "same_temperature_delta": comparison["margin_delta_mm"][side],
                        "governing_temperature_delta": "0",
                    })
                    self.assertEqual({key: change[key] for key in attribution}, attribution)
                    bound = "lower_bound" if side == "minimum" else "upper_bound"
                    baseline_trace = report["baseline"][bound]
                    self.assertEqual(change["baseline_temperature"], baseline_trace["temperature"])
                    self.assertEqual(change["candidate_temperature"], candidate["evaluation"][bound]["temperature"])
                    self.assertEqual([(term["physical_id"], term["baseline_contribution"]) for term in change["terms"]],
                                     [(term["physical_id"], term["contribution"]) for term in baseline_trace["terms"]])
                    sign = 1 if side == "minimum" else -1
                    delta = sum(Fraction(term["candidate_contribution"]) - Fraction(term["baseline_contribution"])
                                for term in change["terms"])
                    self.assertEqual(sign * delta, Fraction(change["same_temperature_delta"]))
                    self.assertEqual(sign * delta + Fraction(change["governing_temperature_delta"]),
                                     Fraction(change["margin_delta"]))
                if scenario["id"] == "governing-temperature-shift":
                    terms = explanation["margins"]["minimum"]["terms"]
                    # At 60 °C both drawing lengths use the same factor of 1.00092.
                    self.assertEqual([term["candidate_contribution"] for term in terms],
                                     ["20.1034782", "-20.043423"])

    def assert_reference_evaluation(self, evaluation, reference, index):
        row = reference["candidates"][index]
        for side, endpoint, offset in (("lower", "cold", 0), ("upper", "hot", 1)):
            trace = evaluation[f"{side}_bound"]
            self.assertEqual(trace["value"], row[f"{endpoint}_bounds_mm"][offset])
            self.assertEqual(trace["temperature"], reference["temperature_endpoints_degC"][offset])
            self.assertEqual([term["contribution"] for term in trace["terms"]], row[f"{side}_signed_terms_mm"])
            self.assertEqual(sum(Fraction(term["contribution"]) for term in trace["terms"]), Fraction(trace["value"]))
        self.assertEqual([[item["limits"]["lower"], item["limits"]["upper"]] for item in evaluation["drawing_limits"]],
                         [reference["reference_drawing_limits_mm"][option] for option in row["option_ids"]])

    def test_terminal_report_alone_answers_reference_decision(self):
        source = load_problem(FIXTURES / "manual-case.json")
        report = build_allocation_report(source, allocate(source.problem))
        terminal = render_terminal(report)
        for line in (
            "Requirement running-clearance: minimum 0.05 mm, maximum 0.15 mm",
            "Baseline | FAIL | limiting side: maximum",
            "Lower bound 0.041143 mm at -20 °C",
            "fixture-bore-1: +20.056531 mm (+1 * 20.056531 mm, lower drawing limit)",
            "fixture-shaft-1: -20.015388 mm (-1 * 20.015388 mm, upper drawing limit)",
            "Upper bound 0.158927 mm at 60 °C",
            "fixture-bore-1: +20.143515 mm (+1 * 20.143515 mm, upper drawing limit)",
            "fixture-shaft-1: -19.984588 mm (-1 * 19.984588 mm, lower drawing limit)",
            "maximum margin -8.9270 µm | FAIL",
            "Selected feasible candidate #2 | PASS",
            "Lower bound 0.0511338 mm at -20 °C",
            "Upper bound 0.1489178 mm at 60 °C",
            "option 'bore-tight' | [-0.025, +0.025] mm -> [-0.015, +0.015] mm",
            "[20.075, 20.125] mm", "[20.085, 20.115] mm", "[19.975, 20.025] mm",
            "minimum: -8.8570 µm -> +1.1338 µm (delta +9.9908 µm)",
            "maximum: -8.9270 µm -> +1.0822 µm (delta +10.0092 µm)",
            "fixture-bore-1: +20.143515 -> +20.1335058 mm signed contribution",
        ):
            self.assertIn(line, terminal)
        upper = report["explanation"]["margins"]["maximum"]
        reference = load("reference.json")["bore_only"]
        self.assertEqual(Fraction(upper["margin_delta"]) * 1000, Fraction(reference["upper_margin_delta_um"]))
        self.assertEqual(report["explanation"]["callout_changes"], [{
            "callout": source.problem["option_groups"][0]["callout"], "option_id": "bore-tight",
            "before": {"lower": "-0.025", "upper": "0.025"}, "after": {"lower": "-0.015", "upper": "0.015"},
        }])
        for encoding in ("cp1252", "cp437", "utf-8"):
            self.assertEqual(terminal.encode(encoding).decode(encoding), terminal)

    def test_terminal_qualifies_every_report_outcome(self):
        expected_text = {
            "two-sided": "Selected feasible candidate #2 | PASS",
            "minimum-only": "minimum margin -13.8570 µm | FAIL",
            "maximum-only": "maximum margin -8.9270 µm | FAIL",
            "impossible": "Closest tested candidate (diagnostic, still fails) #3 | FAIL",
            "interrupted-no-feasible": "Closest evaluated so far (diagnostic, still fails) #0 | FAIL",
            "interrupted-with-feasible": "Provisional best among evaluated candidates #1 | PASS",
            "zero-tested": "Stopped before evaluating any assignment | evaluated 0 of 4",
            "tied-score": "Best: #1, #2 (tie)",
            "no-objective": "Ranking unavailable: no objective",
            "missing-score": "Ranking unavailable: missing scores",
            "governing-temperature-shift": "Governing temperature 60 -> -20 °C | margin delta -0.1104 µm",
            "closest-minimax-tie": "Closest tested candidate (diagnostic, still fails) #1 | FAIL",
        }
        for scenario in load("report-cases.json"):
            with self.subTest(scenario=scenario["id"]):
                report = _run_scenario(scenario)
                terminal = render_terminal(report)
                self.assertIn(expected_text[scenario["id"]], terminal)
                self.assertIn("Lower bound", terminal)
                self.assertIn("Upper bound", terminal)
                self.assertIn("Requirement running-clearance", terminal)
                for side in {"minimum", "maximum"} - scenario["limits_mm"].keys():
                    self.assertNotIn(f"{side} margin ", terminal)
                if "closest" in report or "explanation" not in report:
                    self.assertNotIn("Selected feasible candidate", terminal)
                if "explanation" not in report:
                    self.assertNotIn("Margin changes from baseline", terminal)
                    self.assertNotIn("Closest", terminal)
                if report["ranking"]["status"] == "unranked":
                    self.assertIn("-> 'shaft-tight' | [-0.01, +0.01] mm deviations", terminal)
                if report["search"]["status"] in ("incomplete", "zero_tested"):
                    self.assertNotIn("Infeasible across all declared assignments", terminal)

    def test_shared_callout_changes_once_and_keeps_distinct_signed_terms(self):
        case = load("shared-callout-case.json")
        case["objective"] = load("manual-case.json")["objective"]
        case["option_groups"][0]["options"][0]["score"] = {"value": "2.25", "source_ref": "fixture source"}
        source = _source(case)
        report = build_allocation_report(source, allocate(source.problem))
        explanation = report["explanation"]
        self.assertEqual(len(explanation["callout_changes"]), 1)
        self.assertEqual(explanation["callout_changes"][0]["option_id"], "a-tight")
        self.assertEqual(explanation["margins"]["minimum"]["terms"][:2], [
            {"physical_id": "a-1", "baseline_contribution": "10", "candidate_contribution": "10"},
            {"physical_id": "a-2", "baseline_contribution": "-10.2", "candidate_contribution": "-10.1"},
        ])
        evaluation = report["feasible_candidates"][0]["evaluation"]
        self.assertEqual(evaluation["margins"], {"minimum": "0", "maximum": "0"})
        self.assertTrue(evaluation["meets_requirement"])
        self.assertEqual(report["feasible_candidates"][0]["assignment"][0]["score"],
                         {"value": "2.25", "source_ref": "fixture source"})

    def test_snapshot_context_and_stopped_search_warnings_stay_structured(self):
        source = load_problem(FIXTURES / "cad-shaped-snapshot.json")
        run = allocate(source.problem, budget={"max_seconds": 0})
        original = deepcopy((source, run))
        report = build_allocation_report(source, run)
        self.assertEqual((source, run), original)
        self.assertEqual(report["source_kind"], "snapshot")
        self.assertEqual(report["search"]["budget"], {"max_seconds": "0"})
        self.assertEqual(report["search"]["status"], "zero_tested")
        self.assertEqual(report["diagnostics"], [*source.diagnostics, *run["diagnostics"]])
        self.assertNotIn("[search.incomplete]", render_terminal(report))
        self.assertIn("warning [search.incomplete]", render_diagnostics(report["diagnostics"]))
        self.assertEqual(render_json(report), render_json(build_allocation_report(source, run)))

    def test_analysis_keeps_exact_small_failure_independent_of_display_context(self):
        case = load("manual-case.json")
        case["requirement"] = {"id": "small-violation", "maximum": quantity("0.158926999999")}
        source = _source(case)
        report = build_analysis_report(source, evaluate(source.problem))
        original = deepcopy(report)
        self.assertEqual(report["baseline"]["margins"], {"maximum": "-0.000000000001"})
        self.assertFalse(report["baseline"]["meets_requirement"])
        self.assertEqual(json.loads(render_json(report)), report)
        with localcontext(prec=4, rounding=ROUND_DOWN):
            terminal = render_terminal(report)
        self.assertEqual(terminal, render_terminal(report))
        self.assertIn("maximum margin -0.000000001 µm | FAIL", terminal)
        self.assertNotIn("minimum margin", terminal)
        self.assertNotIn("search", report)
        self.assertEqual(report, original)

    def test_fatal_diagnostic_document_and_terminal_preserve_context(self):
        diagnostic = {
            "code": "cad.tolerance_unresolved", "severity": "error", "message": "The bore limit is unresolved.",
            "recovery": "Supply manual drawing deviations.", "field": "/dimensions/0/tolerance",
            "logical_id": "bore", "source_ref": "Assembly Ω",
        }
        report = build_diagnostic_report("extract", [diagnostic])
        self.assertEqual(json.loads(render_json(report).encode("utf-8")), {
            "kind": "diagnostic_result", "schema_version": 1, "command": "extract", "diagnostics": [diagnostic],
        })
        terminal = render_diagnostics(report["diagnostics"])
        self.assertIn("error [cad.tolerance_unresolved]", terminal)
        self.assertIn("field='/dimensions/0/tolerance', logical_id='bore', source_ref='Assembly Ω'", terminal)
        self.assertIn("Supply manual drawing deviations.", terminal)
        self.assertEqual(render_diagnostics([]), "")
