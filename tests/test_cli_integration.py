"""Exercise production CLI routes against the independent acceptance fixtures."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from acceptance_oracle import FIXTURES, diagnostic_inputs, load, scenario_case
from stackopt.allocation import allocate
from stackopt.cli import main


class ProductionCliTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="stackopt-cli-")
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.output = self.work / "result.json"

    def document(self, value):
        path = self.work / "input.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run_cli(self, *argv):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "stackopt", *map(str, argv)],
            capture_output=True, encoding="utf-8", timeout=30, check=False,
        )
        return result.returncode, result.stdout, result.stderr

    def invoke(self, *argv):
        with redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr:
            code = main(list(map(str, argv)))
        return code, stdout.getvalue(), stderr.getvalue()

    def result(self):
        return json.loads(self.output.read_text(encoding="utf-8"))

    def test_analyzed_violation_and_offline_replay(self):
        baseline = None
        for filename in ("manual-case.json", "cad-shaped-snapshot.json"):
            path = FIXTURES / filename
            code, stdout, stderr = self.run_cli("analyze", path, "--json", self.output)
            self.assertEqual((code, stdout), (0, ""), stderr)
            if filename == "cad-shaped-snapshot.json":
                self.assertIn("warning [cad.tolerance_discrepancy]", stderr)
            else:
                self.assertEqual(stderr, "")
            report = self.result()
            self.assertEqual(report["kind"], "analysis_result")
            observed = report["baseline"]
            self.assertFalse(observed["meets_requirement"])
            reference = load("reference.json")["candidates"][0]
            for side, endpoint, offset in (("lower", "cold", 0), ("upper", "hot", 1)):
                bound = observed[f"{side}_bound"]
                self.assertEqual(bound["value"], reference[f"{endpoint}_bounds_mm"][offset])
                self.assertEqual([term["contribution"] for term in bound["terms"]],
                                 reference[f"{side}_signed_terms_mm"])
            if baseline is not None:
                # The snapshot preserves CAD provenance alongside the same physical result.
                for key in ("margins", "lower_bound", "upper_bound"):
                    self.assertEqual(observed[key], baseline[key])
            baseline = observed

            original = self.output.read_bytes()
            self.assertEqual(self.run_cli("analyze", path, "--json", self.output), (0, "", stderr))
            self.assertEqual(self.output.read_bytes(), original)

    def test_allocation_manifest_through_production_handlers(self):
        for scenario in load("report-cases.json"):
            with self.subTest(scenario=scenario["id"]):
                source = self.document(scenario_case(scenario))
                expected = scenario["expected"]
                control = scenario.get("search_control", {})
                if control:
                    stop_after = control.get("interrupt_after")
                    checks = iter(range(stop_after + 1)) if stop_after is not None else None
                    with patch("stackopt.cli.allocate", side_effect=lambda problem, **kwargs: allocate(
                        problem, budget=control.get("budget"),
                        should_stop=None if checks is None else lambda: next(checks) >= stop_after,
                    )):
                        code, stdout, stderr = self.invoke("allocate", source, "--json", self.output)
                    self.assertEqual(code, 7)
                    self.assertIn("warning [search.incomplete]", stderr)
                else:
                    code, stdout, stderr = self.run_cli("allocate", source, "--json", self.output)
                    self.assertEqual(code, 6 if expected["search"]["status"] == "infeasible" else 0)
                    self.assertEqual(stderr, "")
                self.assertEqual(stdout, "")
                report = self.result()
                self.assertEqual(report["search"], expected["search"])
                self.assertEqual([item["index"] for item in report["feasible_candidates"]],
                                 expected["feasible_indices"])
                self.assertEqual(report["baseline"]["margins"], expected["baseline_margins_mm"])
                if "comparison" in expected:
                    comparison = expected["comparison"]
                    explanation = report["explanation"]
                    self.assertEqual(explanation["role"], comparison["role"])
                    self.assertEqual(explanation["candidate_index"], comparison["candidate_index"])
                    self.assertEqual({side: item["margin_delta"] for side, item in explanation["margins"].items()},
                                     comparison["margin_delta_mm"])
                else:
                    self.assertNotIn("explanation", report)

    def test_ctrl_c_preserves_completed_search_prefix(self):
        from stackopt.allocation import _evaluate

        evaluations = 0

        def interrupt_first_candidate(problem):
            nonlocal evaluations
            evaluations += 1
            if evaluations == 2:
                signal.raise_signal(signal.SIGINT)
            return _evaluate(problem)

        previous = signal.getsignal(signal.SIGINT)
        with patch("stackopt.allocation._evaluate", side_effect=interrupt_first_candidate):
            code, stdout, stderr = self.invoke("allocate", FIXTURES / "manual-case.json")
        self.assertIs(signal.getsignal(signal.SIGINT), previous)
        self.assertEqual(code, 7)
        self.assertIn("evaluated 1 of 4", stdout)
        self.assertIn("Closest evaluated so far", stdout)
        self.assertIn("warning [search.incomplete]", stderr)

    def test_terminal_output_for_bore_only_decision(self):
        code, stdout, stderr = self.run_cli("allocate", FIXTURES / "manual-case.json")
        self.assertEqual((code, stderr), (0, ""))
        for expected in (
            "Requirement running-clearance",
            "minimum margin -8.8570 µm | FAIL",
            "maximum margin -8.9270 µm | FAIL",
            "fixture-bore-1: +20.143515 mm",
            "fixture-shaft-1: -19.984588 mm",
            "option 'bore-tight' | [-0.025, +0.025] mm -> [-0.015, +0.015] mm",
            "maximum: -8.9270 µm -> +1.0822 µm (delta +10.0092 µm)",
        ):
            self.assertIn(expected, stdout)

    def test_fatal_boundaries_preserve_output_and_keep_stdout_empty(self):
        source = FIXTURES / "manual-case.json"
        self.output.write_bytes(b"previous result")
        code, stdout, stderr = self.run_cli("analyze", self.document({}), "--json", self.output)
        self.assertEqual((code, stdout), (3, ""))
        error = json.loads(stderr)
        self.assertEqual((error["kind"], error["schema_version"], error["command"]),
                         ("diagnostic_result", 1, "analyze"))
        self.assertEqual(error["diagnostics"][0]["code"], "input.kind")
        self.assertEqual(self.output.read_bytes(), b"previous result")

        with patch("stackopt.cli.evaluate", side_effect=RuntimeError("simulated internal failure")):
            code, stdout, stderr = self.invoke("analyze", source, "--json", self.output)
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(json.loads(stderr)["diagnostics"][0]["code"], "internal.failure")
        self.assertEqual(self.output.read_bytes(), b"previous result")

        impossible = next(row for row in load("report-cases.json") if row["id"] == "impossible")
        with patch.object(os, "replace", side_effect=OSError("simulated write failure")):
            code, stdout, stderr = self.invoke(
                "allocate", self.document(scenario_case(impossible)), "--json", self.output,
            )
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(json.loads(stderr)["diagnostics"][0]["code"], "io.write_failed")
        self.assertEqual(self.output.read_bytes(), b"previous result")
        self.assertFalse(list(self.work.glob(".stackopt-*.tmp")))

    def test_redirected_diagnostic_json_is_utf8(self):
        missing = self.work / "missing-Ω.json"
        with patch.dict(os.environ, {"PYTHONIOENCODING": "ascii"}):
            code, stdout, stderr = self.run_cli("analyze", missing, "--json", self.output)
        self.assertEqual((code, stdout), (3, ""))
        self.assertEqual(json.loads(stderr)["diagnostics"][0]["source_ref"], str(missing))

    def test_extract_validates_first_and_preserves_binding_diagnostics(self):
        fixture = load("cad-shaped-snapshot.json")
        self.output.write_bytes(b"previous snapshot")
        args = ("extract", "solidworks", "--active", "--out", self.output, "--case")
        with patch("stackopt.adapters.solidworks.extract_active") as extract:
            code, stdout, stderr = self.invoke(*args, FIXTURES / "manual-case.json")
            self.assertEqual((code, stdout), (3, ""))
            self.assertIn("input.invalid_operation", stderr)
            extract.assert_not_called()

            bound_case, records = diagnostic_inputs(load("diagnostic-cases.json")[-1])
            extract.return_value = records
            case = self.document(bound_case)
            code, stdout, stderr = self.invoke(*args, case)
            self.assertEqual((code, stdout), (5, ""))
            self.assertIn("cad.tolerance_unresolved", stderr)
            self.assertIn("/dimensions/1/tolerance", stderr)
            self.assertIn("warning [cad.tolerance_unresolved]", stderr)
            self.assertIn("error [cad.tolerance_unresolved]", stderr)
            self.assertEqual(self.output.read_bytes(), b"previous snapshot")

            extract.return_value = fixture["extraction_records"]
            code, stdout, stderr = self.invoke(*args, case)
            self.assertEqual(code, 0, stderr)
            self.assertIn("2 CAD bindings", stdout)
            self.assertIn("warning [cad.tolerance_discrepancy]", stderr)
            snapshot = self.result()
            for key in ("kind", "schema_version", "case", "problem", "extraction_records"):
                self.assertEqual(snapshot[key], fixture[key])
            self.assertEqual([item["code"] for item in snapshot["diagnostics"]],
                             ["cad.tolerance_discrepancy"])
