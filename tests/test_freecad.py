import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from stackopt.cli import main
from stackopt.snapshot import load_problem


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
FREECAD = EXAMPLES / "cad" / "freecad"
MANUAL = EXAMPLES / "acceptance-v1" / "manual-case.json"


class FreeCadCliTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.output = self.work / "snapshot.json"
        self.case = FREECAD / "case.json"
        self.records = FREECAD / "records.json"

    def extract(self, records=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main([
                "extract", "freecad", "--case", str(self.case), "--records", str(records or self.records),
                "--out", str(self.output),
            ])
        return status, out.getvalue(), err.getvalue()

    def test_offline_record_import_and_replay(self):
        status, out, err = self.extract()
        self.assertEqual(status, 0, err)
        self.assertIn("2 CAD bindings", out)
        self.assertIn("cad.source_state", err)
        self.assertEqual(load_problem(self.output).problem, load_problem(MANUAL).problem)

    def test_protocol_errors_preserve_destination(self):
        records = json.loads(self.records.read_text(encoding="utf-8"))
        mixed = deepcopy(records)
        for role in ("document", "assembly"):
            mixed[1]["source"][role]["id"] += "-other"
        native_tolerance = deepcopy(records)
        native_tolerance[0]["tolerance"] = {"status": "supported", "deviations": {
            "lower": {"value": "-0.01", "unit": "mm"}, "upper": {"value": "0.01", "unit": "mm"},
        }}
        wrong_observation = deepcopy(records)
        wrong_observation[0]["source"]["dimension_id"] = "Radius"
        self.output.write_bytes(b"existing snapshot")
        for batch, diagnostic in (
            (mixed, "one document"),
            (native_tolerance, "qualified native tolerances"),
            (wrong_observation, "match the requested target"),
        ):
            with self.subTest(diagnostic=diagnostic):
                path = self.work / "invalid.records.json"
                path.write_text(json.dumps(batch), encoding="utf-8")
                status, out, err = self.extract(path)
                self.assertEqual((status, out), (5, ""), err)
                self.assertIn("cad.protocol_error", err)
                self.assertIn(diagnostic, err)
                self.assertEqual(self.output.read_bytes(), b"existing snapshot")

    def test_selection_of_native_tolerance_has_no_fallback(self):
        case = json.loads(self.case.read_text(encoding="utf-8"))
        case["dimensions"][0]["tolerance"] = {"kind": "cad"}
        self.case = self.work / "bad-case.json"
        self.case.write_text(json.dumps(case), encoding="utf-8")
        status, out, err = self.extract()
        self.assertEqual((status, out), (5, ""), err)
        self.assertIn("error [cad.tolerance_unresolved]", err)
        self.assertFalse(self.output.exists())

    def test_crossed_adapter_and_transport_are_usage_errors(self):
        for adapter, args in (("solidworks", ["--records", str(self.records)]), ("freecad", ["--active"])):
            with self.subTest(adapter=adapter), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(["extract", adapter, "--case", str(self.case), "--out", str(self.output), *args])
                self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.output.exists())
