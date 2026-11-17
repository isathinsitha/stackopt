"""Parse command arguments and dispatch to application handlers."""

import argparse
from collections.abc import Sequence
from fractions import Fraction
from io import TextIOWrapper
from pathlib import Path
import signal
import sys
from threading import current_thread, main_thread
from typing import Protocol, TextIO

from .allocation import AllocationRun, allocate
from .analysis import evaluate
from .case import ExtractionError, cad_bindings, load_case, load_extraction_records, resolve_case
from .contract_validation import parse_decimal_text
from .contracts import AllocationResult, AnalysisResult, SearchBudget
from .diagnostics import ContractError, Diagnostic, ExitStatus
from .report import (
    build_allocation_report,
    build_analysis_report,
    build_diagnostic_report,
    render_diagnostics,
    render_json,
    render_terminal,
)
from .snapshot import AnalysisInput, load_problem, write_snapshot, write_utf8_atomic


class CommandHandlers(Protocol):
    """Application entry points that own case and output I/O."""

    def extract(
        self, case: Path, *, adapter: str, snapshot_out: Path, records: Path | None = None,
    ) -> object: ...

    def analyze(self, source: Path, *, json_out: Path | None) -> object: ...

    def allocate(
        self, source: Path, *, json_out: Path | None, budget: SearchBudget[Fraction] | None = None,
    ) -> object: ...


_SEARCH_EXITS = {
    "complete": ExitStatus.SUCCESS,
    "infeasible": ExitStatus.ALLOCATION_INFEASIBLE,
    "incomplete": ExitStatus.ALLOCATION_INCOMPLETE,
    "zero_tested": ExitStatus.ALLOCATION_INCOMPLETE,
}


def _write_stream(stream: TextIO, text: str) -> None:
    if not text:
        return
    if isinstance(stream, TextIOWrapper) and not stream.isatty():
        stream.buffer.write(text.encode("utf-8"))
        stream.buffer.flush()
    else:
        stream.write(text)
        stream.flush()


def _write_report(report: AnalysisResult | AllocationResult, json_out: Path | None) -> None:
    if json_out is None:
        _write_stream(sys.stdout, render_terminal(report))
    else:
        write_utf8_atomic(json_out, render_json(report))
    _write_stream(sys.stderr, render_diagnostics(report["diagnostics"]))


def _search(inputs: AnalysisInput, budget: SearchBudget[Fraction] | None = None) -> AllocationRun:
    """Ask the allocator to stop between candidates when Ctrl+C arrives."""
    if current_thread() is not main_thread():
        return allocate(inputs.problem, budget=budget)

    interrupted = False

    def request_stop(signum, frame):
        nonlocal interrupted
        interrupted = True

    previous = signal.signal(signal.SIGINT, request_stop)
    try:
        return allocate(inputs.problem, budget=budget, should_stop=lambda: interrupted)
    finally:
        signal.signal(signal.SIGINT, previous)


class _ProductionHandlers:
    def extract(
        self, case: Path, *, adapter: str, snapshot_out: Path, records: Path | None = None,
    ) -> ExitStatus:
        document = load_case(case)
        bindings = cad_bindings(document, adapter=adapter)

        if records is None:
            from .adapters.solidworks import extract_active

            observations = extract_active(bindings)
        else:
            observations = load_extraction_records(records)
        resolved = resolve_case(document, observations)
        write_snapshot(snapshot_out, resolved)
        _write_stream(sys.stdout, f"Wrote snapshot to {snapshot_out} ({len(bindings)} CAD bindings).\n")
        _write_stream(sys.stderr, render_diagnostics(resolved.diagnostics))
        return ExitStatus.SUCCESS

    def analyze(self, source: Path, *, json_out: Path | None) -> ExitStatus:
        inputs = load_problem(source)
        _write_report(build_analysis_report(inputs, evaluate(inputs.problem)), json_out)
        return ExitStatus.SUCCESS

    def allocate(
        self, source: Path, *, json_out: Path | None, budget: SearchBudget[Fraction] | None = None,
    ) -> ExitStatus:
        inputs = load_problem(source)
        report = build_allocation_report(inputs, _search(inputs, budget))
        status = _SEARCH_EXITS[report["search"]["status"]]
        _write_report(report, json_out)
        return status


def _evaluation_limit(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative whole number")
    return value


def _seconds_limit(text: str) -> Fraction:
    try:
        value = parse_decimal_text(text, "")
    except ContractError:
        raise argparse.ArgumentTypeError('expected a nonnegative decimal such as "30" or "2.5"') from None
    if value < 0:
        raise argparse.ArgumentTypeError('expected a nonnegative decimal such as "30" or "2.5"')
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stackopt",
        description="Deterministic dimensional tolerance analysis",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser(
        "extract", help="Resolve a CAD-bound case into a snapshot", allow_abbrev=False
    )
    extract.add_argument("adapter", choices=("solidworks", "freecad"), help="CAD adapter")
    source = extract.add_mutually_exclusive_group(required=True)
    source.add_argument("--active", action="store_true", help="Read the active SOLIDWORKS assembly")
    source.add_argument("--records", type=Path, help="Read a FreeCAD export JSON file")
    extract.add_argument("--case", type=Path, required=True, help="CAD-bound case JSON")
    extract.add_argument("--out", type=Path, required=True, help="Output snapshot JSON")

    for name, help_text in (
        ("analyze", "Evaluate the baseline clearance"),
        ("allocate", "Evaluate declared tolerance options"),
    ):
        command = commands.add_parser(name, help=help_text, allow_abbrev=False)
        command.add_argument("source", type=Path, help="Manual case or saved snapshot JSON")
        command.add_argument("--json", type=Path, help="Write the result to this JSON file")
        if name == "allocate":
            command.add_argument("--max-evaluations", type=_evaluation_limit, metavar="N",
                                 help="Stop after evaluating N assignments")
            command.add_argument("--max-seconds", type=_seconds_limit, metavar="SECONDS",
                                 help="Stop starting new assignments after this many seconds")

    return parser


def dispatch(args: argparse.Namespace, handlers: CommandHandlers) -> object:
    """Invoke the selected handler with parsed arguments and return its outcome."""
    if args.command == "extract":
        records = getattr(args, "records", None)
        if records is not None:
            return handlers.extract(args.case, adapter=args.adapter, snapshot_out=args.out, records=records)
        return handlers.extract(args.case, adapter=args.adapter, snapshot_out=args.out)
    if args.command == "analyze":
        return handlers.analyze(args.source, json_out=args.json)
    if args.command == "allocate":
        budget: SearchBudget[Fraction] = {}
        if args.max_evaluations is not None:
            budget["max_evaluations"] = args.max_evaluations
        if args.max_seconds is not None:
            budget["max_seconds"] = args.max_seconds
        if budget:
            return handlers.allocate(args.source, json_out=args.json, budget=budget)
        return handlers.allocate(args.source, json_out=args.json)
    raise ValueError(f"Unknown command: {args.command}")


def main(
    argv: Sequence[str] | None = None, *, handlers: CommandHandlers | None = None
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "extract" and args.active != (args.adapter == "solidworks"):
        parser.error("extract solidworks requires --active and extract freecad requires --records")
    application = _ProductionHandlers() if handlers is None else handlers
    diagnostics: Sequence[Diagnostic]
    try:
        outcome = dispatch(args, application)
        # Injected routing handlers may return arbitrary objects.
        return int(outcome) if isinstance(outcome, ExitStatus) else 0
    except ExtractionError as exc:
        status, diagnostics = exc.exit_status, exc.diagnostics
    except ContractError as exc:
        status, diagnostics = exc.exit_status, [exc.diagnostic]
    except (Exception, KeyboardInterrupt) as exc:
        status = ExitStatus.EXECUTION_FAILURE
        diagnostics = [{
            "code": "internal.failure",
            "severity": "error",
            "message": f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
            "recovery": "Retry the command or report the error with the command and input.",
        }]

    if getattr(args, "json", None) is not None:
        _write_stream(sys.stderr, render_json(build_diagnostic_report(args.command, diagnostics)))
    else:
        _write_stream(sys.stderr, render_diagnostics(diagnostics))
    return int(status)
