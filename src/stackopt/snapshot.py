"""Persist resolved inputs atomically and validate offline replay."""

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Literal, cast

from .case import (
    ResolvedCase,
    _array,
    _callout,
    _check_alpha,
    _check_resolved_identities,
    _choice,
    _deviations,
    _diagnostics,
    _drawing_limits,
    _duplicate,
    _identity_error,
    _internal,
    _invalid,
    _load_json,
    _nonnegative_length,
    _object,
    _parse_case,
    _parse_common,
    _read_observations,
    _text,
    _tolerance_error,
    resolve_case,
)
from .contract_validation import format_decimal_text, parse_decimal_text, validate_header
from .contracts import (
    SCHEMA_VERSION,
    CaseDocument,
    DecimalText,
    ResolvedDimension,
    ResolvedProblem,
    SnapshotDocument,
)
from .diagnostics import ContractError, Diagnostic, ExitStatus


@dataclass(frozen=True)
class AnalysisInput:
    """Canonical numerical inputs and context shared by offline commands."""

    problem: ResolvedProblem[Fraction]
    case_id: str
    source_kind: Literal["case", "snapshot"]
    diagnostics: list[Diagnostic]


def _snapshot_dimension(
    value: object, path: str,
) -> ResolvedDimension[Fraction]:
    data = _object(value, path, (
        "logical_id", "physical_id", "callout", "nominal", "alpha", "drawing_limits", "tolerance_source",
    ))
    nominal_path = f"{path}/nominal"
    nominal = _nonnegative_length(parse_decimal_text(data["nominal"], nominal_path), nominal_path)
    limit_path = f"{path}/drawing_limits"
    limits = _object(data["drawing_limits"], limit_path, ("deviations", "lower", "upper"))
    deviations = _deviations(limits["deviations"], f"{limit_path}/deviations", parse_decimal_text)
    expected = _drawing_limits(nominal, deviations, f"{limit_path}/lower")
    lower = parse_decimal_text(limits["lower"], f"{limit_path}/lower")
    upper = parse_decimal_text(limits["upper"], f"{limit_path}/upper")
    for side, bound, limit in (("lower", lower, expected["lower"]), ("upper", upper, expected["upper"])):
        if limit != bound:
            _invalid("input.invalid_value", "The drawing limit does not equal nominal plus deviation.",
                     "Supply the matching absolute drawing limit.", f"{limit_path}/{side}")
    source = _choice(data["tolerance_source"], f"{path}/tolerance_source", "manual", "cad")
    return {
        "logical_id": _text(data["logical_id"], f"{path}/logical_id"),
        "physical_id": _text(data["physical_id"], f"{path}/physical_id"),
        "callout": _callout(data["callout"], f"{path}/callout"),
        "nominal": nominal,
        "alpha": parse_decimal_text(data["alpha"], f"{path}/alpha"),
        "drawing_limits": {"deviations": deviations, "lower": lower, "upper": upper},
        "tolerance_source": cast(Literal["manual", "cad"], source),
    }


def validate_snapshot(document: object) -> AnalysisInput:
    """Validate a v1 snapshot and return its stored problem as exact fractions."""
    validate_header(document, "snapshot")
    data = _object(document, "", ("kind", "schema_version", "case", "problem", "extraction_records", "diagnostics"))
    case = _parse_case(data["case"], "/case")
    records = _array(data["extraction_records"], "/extraction_records")
    observations = _read_observations(case, records, "/extraction_records", replay=True)

    raw_problem = _object(data["problem"], "/problem",
                          ("scope", "chain", "requirement", "model", "dimensions", "option_groups"),
                          ("objective",))
    problem = _parse_common(raw_problem, "/problem", parse_decimal_text, parse_decimal_text)
    for key in ("scope", "chain", "requirement", "model", "option_groups", "objective"):
        if problem.get(key) != case.common.get(key):
            _invalid("input.invalid_value", "The stored value disagrees with the embedded case.",
                     "Supply the original complete snapshot.", f"/problem/{key}")

    spec_indices = {item.spec["logical_id"]: index for index, item in enumerate(case.dimensions)}
    seen: set[str] = set()
    for index, raw_dimension in enumerate(_array(raw_problem["dimensions"], "/problem/dimensions", nonempty=True)):
        pointer = f"/problem/dimensions/{index}"
        dimension = _snapshot_dimension(raw_dimension, pointer)
        identifier = dimension["logical_id"]
        if identifier in seen:
            _duplicate(f"{pointer}/logical_id")
        if identifier not in spec_indices:
            _identity_error(f"{pointer}/logical_id", "The stored dimension has no declaration in the case.")
        seen.add(identifier)
        spec_index = spec_indices[identifier]
        item = case.dimensions[spec_index]
        spec = item.spec
        expected_source = spec["tolerance"]["kind"]
        identities: tuple[tuple[str, object, object], ...] = (
            ("physical_id", dimension["physical_id"], spec["physical_id"]),
            ("callout", dimension["callout"], spec["callout"]),
            ("tolerance_source", dimension["tolerance_source"], expected_source),
        )
        for field, stored, declared in identities:
            if stored != declared:
                _identity_error(f"{pointer}/{field}", "The stored identity or source disagrees with the case.")
        _check_alpha(dimension["alpha"], problem["model"], f"{pointer}/alpha")
        observation = observations.get(identifier)
        nominal = item.nominal if observation is None else observation.nominal
        deviations = item.deviations
        if expected_source == "cad":
            if observation is None:
                _internal(f"CAD dimension {identifier!r} has no extraction record.")
            deviations = observation.deviations
            if deviations is None:
                raise ContractError(_tolerance_error(item, spec_index, "/case"), ExitStatus.INVALID_INPUT)
        quantities: tuple[tuple[str, object, object], ...] = (
            ("alpha", dimension["alpha"], item.alpha),
            ("nominal", dimension["nominal"], nominal),
            ("drawing_limits/deviations", dimension["drawing_limits"]["deviations"], deviations),
        )
        for field, actual, expected in quantities:
            if actual != expected:
                _invalid("input.invalid_value", "The stored quantity disagrees with its frozen source.",
                         "Supply the original complete snapshot.", f"{pointer}/{field}")
        problem["dimensions"].append(dimension)
    if seen != spec_indices.keys():
        _invalid("input.required", "Declared dimensions are missing from the stored problem.",
                 "Supply the original complete snapshot.", "/problem/dimensions")
    # The check applies to all stored dimensions, including CAD-backed aliases.
    _check_resolved_identities(problem, "/problem")

    diagnostics = _diagnostics(data["diagnostics"], "/diagnostics")
    for index, diagnostic in enumerate(diagnostics):
        pointer = f"/diagnostics/{index}"
        if diagnostic["severity"] != "warning":
            _invalid("input.invalid_value", "A complete snapshot may only contain warnings.",
                     "Supply a complete resolved snapshot.", f"{pointer}/severity")
        if "logical_id" in diagnostic and diagnostic["logical_id"] not in seen:
            _identity_error(f"{pointer}/logical_id", "The warning references an undeclared dimension.")
    return AnalysisInput(problem, case.document["case_id"], "snapshot", diagnostics)


def _encode_fractions(value: object) -> object:
    if isinstance(value, Fraction):
        return format_decimal_text(value)
    if isinstance(value, dict):
        return {key: _encode_fractions(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode_fractions(item) for item in value]
    return value


def make_snapshot(resolved: ResolvedCase) -> SnapshotDocument:
    """Build a validated JSON-ready snapshot from the resolved case and evidence."""
    document: SnapshotDocument = {
        "kind": "snapshot",
        "schema_version": SCHEMA_VERSION,
        "case": deepcopy(resolved.case),
        "problem": cast(ResolvedProblem[DecimalText], _encode_fractions(resolved.problem)),
        "extraction_records": deepcopy(resolved.extraction_records),
        "diagnostics": deepcopy(resolved.diagnostics),
    }
    validate_snapshot(document)
    return document


def write_snapshot(path: Path, resolved: ResolvedCase) -> None:
    """Save a complete snapshot by replacing the destination from its own directory."""
    document = make_snapshot(resolved)
    write_utf8_atomic(path, json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _output_mode(path: Path) -> int:
    """Keep an existing file's permissions, or apply the process umask to a new file.

    NamedTemporaryFile creates owner-only files, and os.replace keeps that mode.
    """
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        # os.umask can only be read by setting it. The CLI writes from one thread.
        mask = os.umask(0)
        os.umask(mask)
        return 0o666 & ~mask


def write_utf8_atomic(path: Path, content: str) -> None:
    """Publish complete UTF-8 text or preserve the previous destination."""
    temporary: Path | None = None
    try:
        encoded = content.encode("utf-8")
        mode = _output_mode(path)
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".stackopt-",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        temporary = None
    except (OSError, ValueError) as exc:
        raise ContractError(
            {"code": "io.write_failed", "severity": "error", "message": f"Could not write {path}: {exc}",
             "recovery": "Check the destination directory and its write permissions.", "source_ref": str(path)},
            ExitStatus.EXECUTION_FAILURE,
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Preserve the original write failure if cleanup also fails.
                pass


def replay_snapshot(path: Path) -> AnalysisInput:
    """Read a saved snapshot without contacting its sources."""
    return validate_snapshot(_load_json(path))


def load_problem(path: Path) -> AnalysisInput:
    """Read one offline command input, either a fully manual case or a snapshot."""
    document = _load_json(path)
    if validate_header(document, "case", "snapshot") == "snapshot":
        return validate_snapshot(document)
    resolved = resolve_case(cast(CaseDocument, document))
    return AnalysisInput(resolved.problem, resolved.case["case_id"], "case", resolved.diagnostics)
