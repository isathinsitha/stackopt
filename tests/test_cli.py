import unittest
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from stackopt.adapters.contract import CadAdapter
from stackopt.cli import CommandHandlers, build_parser, dispatch, main


class CliTests(unittest.TestCase):
    def test_routes_manual_inputs(self):
        handlers = Mock(spec=CommandHandlers)

        def read_manual(source, *, json_out):
            self.assertEqual(source.read_text(encoding="utf-8"), "stub manual input")

        handlers.analyze.side_effect = read_manual
        handlers.allocate.side_effect = read_manual
        with TemporaryDirectory() as directory:
            source = Path(directory) / "manual case.json"
            source.write_text("stub manual input", encoding="utf-8")
            report = Path(directory) / "result.json"

            self.assertEqual(main(["analyze", str(source)], handlers=handlers), 0)
            self.assertEqual(
                main(["allocate", str(source), "--json", str(report)], handlers=handlers), 0
            )

            handlers.analyze.assert_called_once_with(source, json_out=None)
            handlers.allocate.assert_called_once_with(source, json_out=report)
            handlers.extract.assert_not_called()

    def test_routes_stub_extraction_then_replay(self):
        handlers = Mock(spec=CommandHandlers)
        stub_adapter = Mock(spec=CadAdapter)
        stub_adapter.extract_active.return_value = ("stub measurement",)

        def extract(case, *, adapter: str, snapshot_out):
            self.assertEqual(adapter, "solidworks")
            binding = case.read_text(encoding="utf-8")
            records = stub_adapter.extract_active((binding,))
            snapshot_out.write_text(records[0], encoding="utf-8")

        def replay(source, *, json_out):
            self.assertEqual(source.read_text(encoding="utf-8"), "stub measurement")

        handlers.extract.side_effect = extract
        handlers.analyze.side_effect = replay
        handlers.allocate.side_effect = replay

        with TemporaryDirectory() as directory:
            case = Path(directory) / "bound case.json"
            case.write_text("stub binding", encoding="utf-8")
            snapshot = Path(directory) / "snapshot.json"
            report = Path(directory) / "result.json"
            extract_args = [
                "extract", "solidworks", "--active", "--case", str(case), "--out", str(snapshot)
            ]

            self.assertEqual(main(extract_args, handlers=handlers), 0)
            handlers.extract.assert_called_once_with(
                case, adapter="solidworks", snapshot_out=snapshot
            )
            self.assertEqual(
                main(["analyze", str(snapshot), "--json", str(report)], handlers=handlers), 0
            )
            self.assertEqual(main(["allocate", str(snapshot)], handlers=handlers), 0)
            handlers.analyze.assert_called_once_with(snapshot, json_out=report)
            handlers.allocate.assert_called_once_with(snapshot, json_out=None)
            stub_adapter.extract_active.assert_called_once_with(("stub binding",))

    def test_routes_allocation_budget_flags(self):
        handlers = Mock(spec=CommandHandlers)
        source = Path("manual.json")
        main(["allocate", str(source), "--max-evaluations", "250", "--max-seconds", "2.5"], handlers=handlers)
        handlers.allocate.assert_called_once_with(
            source, json_out=None, budget={"max_evaluations": 250, "max_seconds": Fraction("2.5")},
        )
        handlers.reset_mock()
        main(["allocate", str(source), "--max-seconds", "0"], handlers=handlers)
        handlers.allocate.assert_called_once_with(source, json_out=None, budget={"max_seconds": 0})

    def test_rejects_invalid_budget_values_before_dispatch(self):
        handlers = Mock(spec=CommandHandlers)
        for argv in (
            ["--max-evaluations", "-1"], ["--max-evaluations", "1.5"], ["--max-evaluations", "ten"],
            ["--max-seconds", "-0.5"], ["--max-seconds", "1e3"], ["--max-seconds", "NaN"],
        ):
            with self.subTest(argv=argv), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as exit_info:
                    main(["allocate", "manual.json", *argv], handlers=handlers)
                self.assertEqual(exit_info.exception.code, 2)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            main(["analyze", "manual.json", "--max-evaluations", "1"], handlers=handlers)
        self.assertEqual(handlers.mock_calls, [])

    def test_dispatch_returns_the_handler_outcome_unchanged(self):
        handlers = Mock(spec=CommandHandlers)
        args = build_parser().parse_args(["allocate", "manual.json"])
        self.assertIs(dispatch(args, handlers), handlers.allocate.return_value)

    def test_help_exits_without_calling_handlers(self):
        handlers = Mock(spec=CommandHandlers)
        for argv in (["--help"], ["extract", "--help"], ["analyze", "--help"], ["allocate", "--help"]):
            with self.subTest(argv=argv), redirect_stdout(StringIO()) as stdout:
                with self.assertRaises(SystemExit) as exit_info:
                    main(argv, handlers=handlers)
                self.assertEqual(exit_info.exception.code, 0)
                self.assertIn("usage: stackopt", stdout.getvalue())
        self.assertEqual(handlers.mock_calls, [])

    def test_usage_errors_exit_before_dispatch(self):
        handlers = Mock(spec=CommandHandlers)
        for argv in (
            [],
            ["extract", "solidworks", "--case", "case.json", "--out", "snapshot.json"],
            ["extract", "freecad", "--active", "--case", "case.json", "--out", "snapshot.json"],
            ["analyze", "case.json", "--active"],
        ):
            with self.subTest(argv=argv), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as exit_info:
                    main(argv, handlers=handlers)
                self.assertEqual(exit_info.exception.code, 2)
        self.assertEqual(handlers.mock_calls, [])

    def test_missing_input_reports_application_error_without_creating_output(self):
        with TemporaryDirectory() as directory, redirect_stderr(StringIO()) as stderr:
            source = Path(directory) / "missing.json"
            output = Path(directory) / "result.json"
            self.assertEqual(main(["allocate", str(source), "--json", str(output)]), 3)
            self.assertIn("io.read_failed", stderr.getvalue())
            self.assertFalse(output.exists())
