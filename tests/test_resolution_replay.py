import json
from copy import deepcopy
from fractions import Fraction
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from acceptance_oracle import FIXTURES, diagnostic_inputs, load, quantity
from stackopt.case import ExtractionError, cad_bindings, load_case, resolve_case
from stackopt.diagnostics import ContractError, ExitStatus
from stackopt.snapshot import load_problem, make_snapshot, replay_snapshot, validate_snapshot, write_snapshot


class ResolutionTests(unittest.TestCase):
    def test_manual_and_adapter_inputs_match_the_frozen_problem(self):
        golden = load("cad-shaped-snapshot.json")
        case = golden["case"]
        records = golden["extraction_records"]
        bindings = cad_bindings(case, adapter="solidworks")
        self.assertEqual(bindings, [
            {"logical_id": spec["logical_id"], "target": spec["nominal"]["target"]}
            for spec in case["dimensions"]
        ])

        resolved = resolve_case(case, records[::-1])
        self.assertEqual(resolved.problem, validate_snapshot(golden).problem)
        cad = make_snapshot(resolved)
        self.assertEqual(cad["problem"], golden["problem"])
        manual = make_snapshot(resolve_case(load_case(FIXTURES / "manual-case.json")))
        expected = deepcopy(cad["problem"])
        expected["dimensions"][1]["tolerance_source"] = "manual"
        self.assertEqual(manual["problem"], expected)
        self.assertEqual(cad["case"], case)
        self.assertEqual(cad["extraction_records"], records)
        self.assertEqual(cad["extraction_records"][0]["nominal"]["unit"], "m")
        self.assertEqual(cad["diagnostics"][0]["code"], "cad.tolerance_discrepancy")
        self.assertEqual(cad["diagnostics"][0]["logical_id"], "bore")
        self.assertEqual(manual["extraction_records"], [])
        self.assertEqual(manual["diagnostics"], [])
        self.assertEqual(load_problem(FIXTURES / "manual-case.json").source_kind, "case")

    def test_contract_examples_replay(self):
        fixture = FIXTURES.parent / "contracts-v1" / "cad-shaped-snapshot.json"
        result = replay_snapshot(fixture)
        self.assertEqual(result.problem["dimensions"][0]["nominal"], Fraction(10))
        self.assertEqual(result.problem["model"]["operating_max"], Fraction(20))
        self.assertEqual(set(result.problem["requirement"]), {"id", "minimum"})

    def test_preflight_rejects_wrong_operation_and_invalid_case(self):
        with self.assertRaises(ContractError) as error:
            cad_bindings(load("manual-case.json"), adapter="solidworks")
        self.assertEqual(error.exception.diagnostic["code"], "input.invalid_operation")

        bound = load("cad-shaped-snapshot.json")["case"]
        with self.assertRaises(ContractError) as error:
            cad_bindings(bound, adapter="other")
        self.assertEqual(error.exception.diagnostic["field"], "/dimensions/0/nominal/target/adapter")
        with self.assertRaises(ContractError) as error:
            resolve_case(bound)
        self.assertEqual(error.exception.exit_status, ExitStatus.INVALID_INPUT)
        bound["chain"]["terms"][0]["logical_id"] = "unknown"
        with self.assertRaises(ContractError) as error:
            cad_bindings(bound, adapter="solidworks")
        self.assertEqual(error.exception.diagnostic["code"], "input.invalid_reference")

    def test_independent_negative_fixtures(self):
        for scenario in load("diagnostic-cases.json"):
            case, records = diagnostic_inputs(scenario)
            with self.subTest(scenario=scenario["id"]), self.assertRaises(ContractError) as error:
                resolve_case(case, records)
            actual = {**error.exception.diagnostic, "exit_status": error.exception.exit_status}
            expected = scenario["expected"]
            self.assertEqual({key: actual[key] for key in expected}, expected)

    def test_exact_conversions_and_explicit_tolerance_selection(self):
        case = load("manual-case.json")
        case["requirement"] = {"id": "gap", "maximum": quantity("1", "in")}
        case["model"]["reference"] = quantity("293.15", "K")
        problem = resolve_case(case).problem
        self.assertEqual(problem["requirement"]["maximum"], Fraction("25.4"))
        self.assertEqual(problem["model"]["reference"], Fraction(20))

        fixture = load("cad-shaped-snapshot.json")
        bore, shaft = fixture["extraction_records"]
        bore["tolerance"]["deviations"] = {"lower": quantity("-0.000025", "m"),
                                           "upper": quantity("0.000025", "m")}
        resolved = resolve_case(fixture["case"], [bore, shaft])
        self.assertEqual(resolved.diagnostics, [])

        warning = {"code": "cad.tolerance_unresolved", "severity": "warning",
                   "message": "Drawing-only tolerance.", "recovery": "Use the drawing."}
        bore["tolerance"] = {"status": "drawing_only", "native_status": {"minimum": 31, "maximum": "Missing"}}
        bore["diagnostics"] = [warning]
        bore["source"]["document"]["state"] = "modified"
        resolved = resolve_case(fixture["case"], [bore, shaft])
        self.assertEqual(resolved.problem["dimensions"][0]["drawing_limits"]["deviations"],
                         {"lower": Fraction("-0.025"), "upper": Fraction("0.025")})
        self.assertEqual([item["code"] for item in resolved.diagnostics],
                         ["cad.tolerance_unresolved", "cad.source_state"])
        self.assertEqual(make_snapshot(resolved)["extraction_records"][0]["tolerance"], bore["tolerance"])

    def test_bound_records_are_complete_unique_and_match_targets(self):
        fixture = load("cad-shaped-snapshot.json")
        case = fixture["case"]
        bore, shaft = fixture["extraction_records"]
        wrong_configuration = deepcopy(bore)
        wrong_configuration["source"]["configuration"] = "wrong-configuration"
        extra = deepcopy(bore)
        extra["logical_id"] = "unrequested"
        native_bool = deepcopy(bore)
        native_bool["tolerance"]["native_status"] = {"minimum": True}
        for records, field in (
            ([bore], "/extraction_records"),
            ([bore, bore], "/extraction_records/1/logical_id"),
            ([bore, shaft, extra], "/extraction_records/2/logical_id"),
            ([wrong_configuration, shaft], "/extraction_records/0/source/configuration"),
            ([native_bool, shaft], "/extraction_records/0/tolerance/native_status/minimum"),
        ):
            with self.subTest(field=field), self.assertRaises(ExtractionError) as error:
                resolve_case(case, records)
            self.assertEqual(error.exception.diagnostic["code"], "cad.protocol_error")
            self.assertEqual(error.exception.diagnostic["field"], field)
            self.assertEqual(error.exception.exit_status, ExitStatus.EXTRACTION_FAILED)

    def test_failed_records_preserve_every_binding_failure(self):
        fixture = load("cad-shaped-snapshot.json")
        records = [
            {
                "kind": "cad_extraction", "schema_version": 1, "status": "failed",
                "logical_id": identifier,
                "diagnostics": [{
                    "code": "cad.binding_missing", "severity": "error",
                    "message": "The dimension was not found.", "recovery": "Check the dimension ID.",
                }],
            }
            for identifier in ("bore", "shaft")
        ]
        with self.assertRaises(ExtractionError) as error:
            resolve_case(fixture["case"], records)
        self.assertEqual(error.exception.exit_status, ExitStatus.EXTRACTION_FAILED)
        self.assertEqual([item["logical_id"] for item in error.exception.diagnostics], ["bore", "shaft"])
        self.assertEqual(error.exception.diagnostic, error.exception.diagnostics[0])

        scenario = load("diagnostic-cases.json")[-1]
        case, unsupported = diagnostic_inputs(scenario)
        with self.assertRaises(ExtractionError) as error:
            resolve_case(case, [unsupported[1], records[0]])
        self.assertEqual(
            [(item["logical_id"], item["severity"], item["code"]) for item in error.exception.diagnostics],
            [("bore", "error", "cad.binding_missing"), ("shaft", "warning", "cad.tolerance_unresolved"),
             ("shaft", "error", "cad.tolerance_unresolved")],
        )

    def test_aliases_keep_physical_and_callout_identity_distinct(self):
        case = load("shared-callout-case.json")
        self.assertEqual(resolve_case(case).problem["scope"], "single_chain")
        original = case["dimensions"][0]
        alias = deepcopy(original)
        alias["logical_id"] = "new-alias"
        case["dimensions"].append(alias)
        resolve_case(case)
        alias["nominal"]["length"] = quantity("11")
        with self.assertRaises(ContractError) as error:
            resolve_case(case)
        self.assertEqual(error.exception.diagnostic["code"], "input.conflicting_identity")
        self.assertTrue(error.exception.diagnostic["field"].endswith("/physical_id"))

        fixture = load("cad-shaped-snapshot.json")
        case = fixture["case"]
        records = fixture["extraction_records"]
        alias = deepcopy(case["dimensions"][0])
        alias["logical_id"] = "copy"
        case["dimensions"].append(alias)
        records.append({**records[0], "logical_id": "copy"})
        resolve_case(case, records)
        alias["physical_id"] = "different-manufactured-dimension"
        with self.assertRaises(ExtractionError) as error:
            resolve_case(case, records)
        self.assertEqual(error.exception.diagnostic["field"], "/extraction_records/2/source")

    def test_rejects_dimensionally_invalid_fields_before_resolution(self):
        for path, value, code in (
            (("dimensions", 0, "alpha", "unit"), "m", "input.unsupported_unit"),
            (("dimensions", 0, "alpha", "value"), "1", "input.invalid_model"),
            (("model", "operating_min"), quantity("-0.01", "K"), "input.invalid_model"),
            (("option_groups", 0, "options", 1, "deviations", "lower"),
             quantity("-30"), "input.invalid_value"),
            (("option_groups", 0, "callout", "revision"), "foreign", "input.invalid_reference"),
            (("dimensions", 1, "logical_id"), "bore", "input.duplicate_id"),
            (("requirement", "x/y~"), "1", "input.unknown_field"),
        ):
            case = load("manual-case.json")
            node = case
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ContractError) as error:
                resolve_case(case)
            self.assertEqual(error.exception.diagnostic["code"], code)


class SnapshotTests(unittest.TestCase):
    def test_reader_rejects_bad_utf8_non_json_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with self.assertRaises(ContractError) as error:
                load_problem(path)
            self.assertEqual(error.exception.diagnostic["code"], "io.read_failed")
            for raw in (b"\xff", b"{", b'{"x": NaN}', b'{"nested": {"x": 1, "x": 2}}'):
                path.write_bytes(raw)
                with self.subTest(raw=raw), self.assertRaises(ContractError) as error:
                    load_problem(path)
                self.assertEqual(error.exception.diagnostic["code"], "input.malformed_json")

    def test_reader_accepts_utf8_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            raw = (FIXTURES / "manual-case.json").read_bytes()
            path.write_bytes(b"\xef\xbb\xbf" + raw)
            self.assertEqual(load_problem(path).problem, load_problem(FIXTURES / "manual-case.json").problem)

    def test_replay_rejects_inconsistent_or_partial_snapshots(self):
        for path, value, field in (
            (("schema_version",), 2, "/schema_version"),
            (("extraction_records",), [], "/extraction_records"),
            (("problem", "dimensions", 0, "nominal"), "NaN", "/problem/dimensions/0/nominal"),
            (("problem", "dimensions", 0, "drawing_limits", "lower"), "20", "/problem/dimensions/0/drawing_limits/lower"),
            (("problem", "dimensions", 0, "physical_id"), "other", "/problem/dimensions/0/physical_id"),
            (("problem", "dimensions", 0, "tolerance_source"), "option", "/problem/dimensions/0/tolerance_source"),
            (("extraction_records", 0, "nominal", "value"), "0.02", "/problem/dimensions/0/nominal"),
            (("diagnostics", 0, "severity"), "error", "/diagnostics/0/severity"),
        ):
            snapshot = load("cad-shaped-snapshot.json")
            node = snapshot
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ContractError) as error:
                validate_snapshot(snapshot)
            self.assertEqual(error.exception.exit_status, ExitStatus.INVALID_INPUT)
            self.assertEqual(error.exception.diagnostic["field"], field)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_atomic_write_uses_umask_or_keeps_existing_mode(self):
        resolved = resolve_case(load("manual-case.json"))
        previous = os.umask(0o022)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "snapshot.json"
                write_snapshot(path, resolved)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
                path.chmod(0o640)
                write_snapshot(path, resolved)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        finally:
            os.umask(previous)

    def test_atomic_failures_leave_original_and_remove_temp_files(self):
        resolved = resolve_case(load("manual-case.json"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            write_snapshot(path, resolved)
            original = path.read_bytes()
            for operation in ("fsync", "replace"):
                with self.subTest(operation=operation), patch(
                    f"stackopt.snapshot.os.{operation}", side_effect=OSError("simulated disk failure"),
                ), self.assertRaises(ContractError) as error:
                    write_snapshot(path, resolved)
                self.assertEqual(error.exception.exit_status, ExitStatus.EXECUTION_FAILURE)
                self.assertEqual(error.exception.diagnostic["code"], "io.write_failed")
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(path.parent.iterdir()), [path])
            resolved.problem["dimensions"][0]["nominal"] += 1
            with self.assertRaises(ContractError):
                write_snapshot(path, resolved)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_old_snapshot_replays_after_case_and_adapter_record_change(self):
        fixture = load("cad-shaped-snapshot.json")
        records = fixture["extraction_records"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "bound.json"
            case_path.write_text(json.dumps(fixture["case"]), encoding="utf-8")
            original, fresh = root / "original.json", root / "fresh.json"
            case = load_case(case_path)
            write_snapshot(original, resolve_case(case, records))
            case["case_id"] = "edited"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            raw_nominal = records[0]["nominal"]
            self.assertEqual(raw_nominal["unit"], "m")
            raw_nominal["value"] = "0.020101"
            write_snapshot(fresh, resolve_case(load_case(case_path), records))
            case_path.unlink()

            with patch("stackopt.snapshot.resolve_case", side_effect=AssertionError("case was re-resolved")), patch(
                "socket.socket", side_effect=AssertionError("network called"),
            ):
                first = load_problem(original)
                edited = replay_snapshot(fresh)
            self.assertEqual(first.case_id, fixture["case"]["case_id"])
            self.assertEqual(edited.case_id, "edited")
            self.assertEqual(first.source_kind, "snapshot")
            self.assertEqual(edited.problem["dimensions"][0]["nominal"] -
                             first.problem["dimensions"][0]["nominal"], Fraction("0.001"))


if __name__ == "__main__":
    unittest.main()
