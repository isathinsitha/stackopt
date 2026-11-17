import json
import unittest
from decimal import localcontext
from fractions import Fraction
from pathlib import Path

from stackopt.contract_validation import (
    cad_double_to_decimal_text,
    format_decimal_text,
    parse_decimal_text,
    parse_requirement,
    validate_header,
)
from stackopt.contracts import callout_key
from stackopt.diagnostics import ContractError, ExitStatus


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "contracts-v1"


class ContractTests(unittest.TestCase):
    def assert_diagnostic(self, error, code, field):
        self.assertEqual(error.exit_status, ExitStatus.INVALID_INPUT)
        self.assertEqual(error.diagnostic["code"], code)
        self.assertEqual(error.diagnostic["field"], field)
        self.assertEqual(error.diagnostic["severity"], "error")
        self.assertTrue(error.diagnostic["recovery"])

    def test_version_requires_an_integer_exactly_equal_to_one(self):
        for invalid in (True, 1.0, "1", 0, 2, None):
            with self.subTest(version=invalid), self.assertRaises(ContractError) as failure:
                validate_header({"kind": "case", "schema_version": invalid}, "case")
            self.assert_diagnostic(failure.exception, "input.schema_version", "/schema_version")
        with self.assertRaises(ContractError) as failure:
            validate_header({"kind": "analysis_result", "schema_version": 1}, "case", "snapshot")
        self.assert_diagnostic(failure.exception, "input.kind", "/kind")

        with self.assertRaises(ContractError) as failure:
            validate_header({"kind": "case", "schema_version": 2}, "case", path="/case")
        self.assert_diagnostic(failure.exception, "input.schema_version", "/case/schema_version")

    def test_exact_decimal_parse_and_format_ignore_decimal_context(self):
        with localcontext() as context:
            context.prec = 3
            for text, expected in (
                ("000.0010822000", "0.0010822"),
                ("-0.00000000000001234567890123456789", "-0.00000000000001234567890123456789"),
                ("-00.00", "0"),
                ("9007199254740993", "9007199254740993"),
            ):
                with self.subTest(text=text):
                    self.assertEqual(format_decimal_text(parse_decimal_text(text, "")), expected)
            self.assertEqual(format_decimal_text(Fraction(3, 40)), "0.075")
        with self.assertRaisesRegex(ValueError, "no finite decimal"):
            format_decimal_text(Fraction(1, 3))

    def test_rejects_unquoted_nonfinite_and_non_fixed_point_quantities(self):
        for invalid in (1, 0.1, False, None, "-Infinity", "NaN", "1e-05", " 1", "0.", ".1"):
            with self.subTest(value=invalid), self.assertRaises(ContractError) as failure:
                parse_decimal_text(invalid, "/requirement/minimum/value")
            self.assert_diagnostic(failure.exception, "input.invalid_decimal", "/requirement/minimum/value")

    def test_cad_double_rendering_preserves_the_round_trip_value(self):
        for observed in (0.01, 1e-12, -0.0, 5e-324, 1.7976931348623157e308):
            with self.subTest(observed=observed):
                text = cad_double_to_decimal_text(observed)
                self.assertNotIn("e", text)
                self.assertEqual(float(text).hex(), observed.hex())
                parse_decimal_text(text, "/nominal/value")
        for nonfinite in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(nonfinite=nonfinite), self.assertRaisesRegex(ValueError, "finite"):
                cad_double_to_decimal_text(nonfinite)

    def test_callout_key_keeps_revision_and_configuration_independent(self):
        self.assertEqual(callout_key({"document_id": "part", "dimension_id": "width"}),
                         ("part", "width", None, None))
        self.assertEqual(callout_key({"document_id": "part", "dimension_id": "width",
                                      "revision": "A", "configuration": "production"}),
                         ("part", "width", "A", "production"))

    def test_accepts_each_requirement_shape_and_equal_limits(self):
        for sides in (
            {"minimum": "0.05"},
            {"maximum": "0.15"},
            {"minimum": "0.05", "maximum": "0.15"},
            {"minimum": "-0.10", "maximum": "-0.1"},
        ):
            with self.subTest(sides=sides):
                limits = parse_requirement({"id": "gap", **sides}, parse_decimal_text)
                expected = {"id": "gap", **{side: Fraction(value) for side, value in sides.items()}}
                self.assertEqual(limits, expected)

    def test_checks_requirement_order_after_the_callers_unit_conversion(self):
        def parse_length(value, path):
            factor = {"mm": Fraction(1), "in": Fraction("25.4")}[value["unit"]]
            return factor * parse_decimal_text(value["value"], f"{path}/value")

        requirement = {
            "id": "gap",
            "minimum": {"value": "1", "unit": "in"},
            "maximum": {"value": "20", "unit": "mm"},
        }
        with self.assertRaises(ContractError) as failure:
            parse_requirement(requirement, parse_length)
        self.assert_diagnostic(failure.exception, "input.reversed_interval", "/requirement/maximum")

    def test_invalid_requirements_have_precise_diagnostics(self):
        for requirement, code, field in (
            ({"id": "gap"}, "input.requirement_missing_limits", "/requirement"),
            ({"id": "gap", "minimum": "1.0001", "maximum": "1"},
             "input.reversed_interval", "/requirement/maximum"),
            ({"id": "gap", "maximum": None}, "input.invalid_decimal", "/requirement/maximum"),
            ({"id": "gap", "wrong/~key": "1"}, "input.unknown_field", "/requirement/wrong~1~0key"),
        ):
            with self.subTest(requirement=requirement), self.assertRaises(ContractError) as failure:
                parse_requirement(requirement, parse_decimal_text)
            self.assert_diagnostic(failure.exception, code, field)

    def test_examples_keep_selected_tolerance_and_declared_margins_visible(self):
        manual = json.loads((EXAMPLES / "manual-case.json").read_text(encoding="utf-8"))
        snapshot = json.loads((EXAMPLES / "cad-shaped-snapshot.json").read_text(encoding="utf-8"))
        report = json.loads((EXAMPLES / "allocation-result.json").read_text(encoding="utf-8"))

        for document, kind in ((manual, "case"), (snapshot, "snapshot"),
                               (snapshot["case"], "case"), (report, "allocation_result")):
            self.assertEqual(validate_header(document, kind), kind)

        record, = snapshot["extraction_records"]
        validate_header(record, "cad_extraction")
        dimension, = snapshot["problem"]["dimensions"]
        self.assertEqual(record["logical_id"], dimension["logical_id"])
        self.assertEqual(Fraction(record["nominal"]["value"]) * 1000, Fraction(dimension["nominal"]))
        self.assertEqual(dimension["tolerance_source"], "manual")
        self.assertEqual(snapshot["diagnostics"][0]["code"], "cad.tolerance_discrepancy")

        requirement = parse_requirement(report["requirement"], parse_decimal_text)
        for evaluation in (report["baseline"], report["feasible_candidates"][0]["evaluation"]):
            self.assertEqual(set(evaluation["margins"]), {"minimum"})
            for key in ("lower_bound", "upper_bound"):
                bound = evaluation[key]
                self.assertEqual(sum(Fraction(term["contribution"]) for term in bound["terms"]),
                                 Fraction(bound["value"]))
            self.assertEqual(Fraction(evaluation["margins"]["minimum"]),
                             Fraction(evaluation["lower_bound"]["value"]) - requirement["minimum"])
        self.assertEqual(report["explanation"]["margins"]["minimum"]["margin_delta"], "0.05")


if __name__ == "__main__":
    unittest.main()
