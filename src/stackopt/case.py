"""Validate authored cases and resolve their dimensions from plain data."""

from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path
from typing import NoReturn, cast, get_args

from .contract_validation import parse_decimal_text, parse_requirement, validate_header
from .contracts import (
    FREECAD_UNCONFIGURED,
    CadBinding,
    CadDocumentRef,
    CadExtractionSuccess,
    CadSource,
    CalloutRef,
    CaseDocument,
    Chain,
    Deviations,
    DimensionSpec,
    DrawingLimits,
    Objective,
    OptionGroup,
    ResolvedDimension,
    ResolvedProblem,
    ThermalModel,
    ToleranceOption,
    callout_key,
)
from .diagnostics import ContractError, Diagnostic, DiagnosticCode, ExitStatus

_ScalarParser = Callable[[object, str], Fraction]
_CalloutKey = tuple[str, str, str | None, str | None]
_DimensionValues = tuple[str, CalloutRef, Fraction, Fraction | None, Deviations[Fraction] | None]
_LENGTH_FACTORS = {"mm": Fraction(1), "m": Fraction(1000), "in": Fraction("25.4")}
_ABSOLUTE_ZERO = Fraction("-273.15")


class ExtractionError(ContractError):
    """A failed extraction with all available per-binding diagnostics."""

    def __init__(self, diagnostics: Sequence[Diagnostic]):
        primary = next(item for item in diagnostics if item["severity"] == "error")
        super().__init__(primary, ExitStatus.EXTRACTION_FAILED)
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True)
class ResolvedCase:
    """Canonical input and frozen-in-use evidence for snapshot creation."""

    case: CaseDocument
    problem: ResolvedProblem[Fraction]
    extraction_records: list[CadExtractionSuccess]
    diagnostics: list[Diagnostic]


@dataclass(frozen=True)
class _DimensionInput:
    spec: DimensionSpec
    alpha: Fraction
    nominal: Fraction | None
    deviations: Deviations[Fraction] | None


@dataclass(frozen=True)
class _CaseInput:
    document: CaseDocument
    common: ResolvedProblem[Fraction]
    dimensions: list[_DimensionInput]


@dataclass(frozen=True)
class _Observation:
    record: CadExtractionSuccess
    nominal: Fraction
    deviations: Deviations[Fraction] | None


def _invalid(code: DiagnosticCode, message: str, recovery: str, path: str) -> NoReturn:
    raise ContractError(
        {"code": code, "severity": "error", "message": message, "recovery": recovery,
         "field": path},
        ExitStatus.INVALID_INPUT,
    )


def _internal(message: str) -> NoReturn:
    """Report a broken invariant. Unlike assert, this survives python -O."""
    raise ContractError({
        "code": "internal.failure",
        "severity": "error",
        "message": message,
        "recovery": "Report the error with the command and input.",
    }, ExitStatus.EXECUTION_FAILURE)


def _pointer(path: str, key: object) -> str:
    token = str(key).replace("~", "~0").replace("/", "~1")
    return f"{path}/{token}"


def _object(
    value: object, path: str, required: tuple[str, ...], optional: tuple[str, ...] = (),
) -> dict[str, object]:
    if not isinstance(value, dict):
        _invalid("input.type", "Expected an object.", "Supply a JSON object.", path)
    for key in required:
        if key not in value:
            _invalid("input.required", "Required field is missing.", f"Supply {key}.", f"{path}/{key}")
    for key in value:
        if key not in required and key not in optional:
            _invalid("input.unknown_field", "Unknown field.", "Remove this field.", _pointer(path, key))
    return value


def _array(value: object, path: str, *, nonempty: bool = False) -> list[object]:
    if not isinstance(value, list):
        _invalid("input.type", "Expected an array.", "Supply a JSON array.", path)
    if nonempty and not value:
        _invalid("input.invalid_value", "The array is empty.", "Supply at least one item.", path)
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        _invalid("input.type", "Expected text.", "Supply a nonblank string.", path)
    if not value.strip():
        _invalid("input.invalid_value", "The string is blank.", "Supply a nonblank string.", path)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _invalid("input.invalid_value", "The string contains an unpaired Unicode surrogate.",
                 "Supply valid UTF-8 text.", path)
    return value


def _choice(value: object, path: str, *allowed: str) -> str:
    token = _text(value, path)
    if token not in allowed:
        _invalid("input.invalid_value", f"Unexpected value {token!r}.",
                 f"Use one of {', '.join(allowed)}.", path)
    return token


def _tag(value: object, path: str, key: str, *allowed: str) -> str:
    if not isinstance(value, dict):
        _invalid("input.type", "Expected an object.", "Supply a JSON object.", path)
    if key not in value:
        _invalid("input.required", "Required field is missing.", f"Supply {key}.", f"{path}/{key}")
    return _choice(value[key], f"{path}/{key}", *allowed)


def _duplicate(path: str) -> NoReturn:
    _invalid("input.duplicate_id", "The identifier is already declared.",
             "Use a unique identifier in this collection.", path)


def _identity_error(path: str, message: str) -> NoReturn:
    _invalid("input.conflicting_identity", message,
             "Correct the linked identities and values.", path)


def _quantity(value: object, path: str, units: Sequence[str]) -> tuple[Fraction, str]:
    data = _object(value, path, ("value", "unit"))
    unit = _text(data["unit"], f"{path}/unit")
    if unit not in units:
        _invalid("input.unsupported_unit", "Unsupported or incompatible unit.",
                 f"Use one of {', '.join(units)}.", f"{path}/unit")
    return parse_decimal_text(data["value"], f"{path}/value"), unit


def _length(value: object, path: str) -> Fraction:
    magnitude, unit = _quantity(value, path, tuple(_LENGTH_FACTORS))
    return magnitude * _LENGTH_FACTORS[unit]


def _temperature(value: object, path: str) -> Fraction:
    magnitude, unit = _quantity(value, path, ("degC", "K"))
    return magnitude + _ABSOLUTE_ZERO if unit == "K" else magnitude


def _deviations(value: object, path: str, parse: _ScalarParser) -> Deviations[Fraction]:
    data = _object(value, path, ("lower", "upper"))
    lower = parse(data["lower"], f"{path}/lower")
    upper = parse(data["upper"], f"{path}/upper")
    if upper < lower:
        _invalid("input.reversed_interval", "The upper deviation is below the lower deviation.",
                 "Supply signed, ordered deviations.", f"{path}/upper")
    return {"lower": lower, "upper": upper}


def _nonnegative_length(value: Fraction, path: str) -> Fraction:
    if value < 0:
        _invalid("input.invalid_value", "The length is negative.", "Supply a nonnegative length.", path)
    return value


def _drawing_limits(
    nominal: Fraction, deviations: Deviations[Fraction], path: str,
) -> DrawingLimits[Fraction]:
    lower = _nonnegative_length(nominal + deviations["lower"], path)
    return {"lower": lower, "upper": nominal + deviations["upper"], "deviations": deviations}


def _callout(value: object, path: str) -> CalloutRef:
    data = _object(value, path, ("document_id", "dimension_id"), ("revision", "configuration"))
    for key, item in data.items():
        _text(item, f"{path}/{key}")
    return cast(CalloutRef, data.copy())


def _chain(value: object, path: str) -> Chain[Fraction]:
    data = _object(value, path, ("id", "terms"))
    identifier = _text(data["id"], f"{path}/id")
    terms = []
    for index, term in enumerate(_array(data["terms"], f"{path}/terms", nonempty=True)):
        pointer = f"{path}/terms/{index}"
        fields = _object(term, pointer, ("logical_id", "coefficient"))
        terms.append({
            "logical_id": _text(fields["logical_id"], f"{pointer}/logical_id"),
            "coefficient": parse_decimal_text(fields["coefficient"], f"{pointer}/coefficient"),
        })
    return {"id": identifier, "terms": terms}


def _model(value: object, path: str, parse: _ScalarParser) -> ThermalModel[Fraction]:
    data = _object(value, path, ("kind", "reference", "operating_min", "operating_max"))
    _choice(data["kind"], f"{path}/kind", "linear_free_expansion")
    reference = parse(data["reference"], f"{path}/reference")
    low = parse(data["operating_min"], f"{path}/operating_min")
    high = parse(data["operating_max"], f"{path}/operating_max")
    for field, temperature in (("reference", reference), ("operating_min", low), ("operating_max", high)):
        if temperature < _ABSOLUTE_ZERO:
            _invalid("input.invalid_model", "Temperature is below absolute zero.",
                     "Use a temperature at or above absolute zero.", f"{path}/{field}")
    if high < low:
        _invalid("input.reversed_interval", "The operating temperature range is reversed.",
                 "Set operating_max at or above operating_min.", f"{path}/operating_max")
    return {"kind": "linear_free_expansion", "reference": reference,
            "operating_min": low, "operating_max": high}


def _check_alpha(alpha: Fraction, model: ThermalModel[Fraction], path: str) -> None:
    endpoints = (model["operating_min"], model["operating_max"])
    if any(1 + alpha * (temperature - model["reference"]) <= 0 for temperature in endpoints):
        _invalid("input.invalid_model", "The thermal scale factor is nonpositive at an operating endpoint.",
                 "Correct the coefficient or temperatures for the free-expansion model.", path)


def _objective(value: object, path: str) -> Objective:
    data = _object(value, path, ("basis", "unit", "source_ref", "context"))
    _choice(data["basis"], f"{path}/basis", "synthetic_penalty", "quoted_cost")
    for key in ("unit", "source_ref", "context"):
        _text(data[key], f"{path}/{key}")
    return cast(Objective, data.copy())


def _option_groups(
    value: object, path: str, parse: _ScalarParser, *, has_objective: bool,
) -> list[OptionGroup[Fraction, Fraction]]:
    groups: list[OptionGroup[Fraction, Fraction]] = []
    seen: set[_CalloutKey] = set()
    for index, group in enumerate(_array(value, path)):
        pointer = f"{path}/{index}"
        fields = _object(group, pointer, ("callout", "options"))
        callout = _callout(fields["callout"], f"{pointer}/callout")
        key = callout_key(callout)
        if key in seen:
            _duplicate(f"{pointer}/callout")
        seen.add(key)
        options: list[ToleranceOption[Fraction, Fraction]] = []
        ids: set[str] = set()
        for option_index, option in enumerate(_array(fields["options"], f"{pointer}/options", nonempty=True)):
            location = f"{pointer}/options/{option_index}"
            data = _object(option, location, ("id", "deviations"), ("score",))
            identifier = _text(data["id"], f"{location}/id")
            if identifier in ids:
                _duplicate(f"{location}/id")
            ids.add(identifier)
            item: ToleranceOption[Fraction, Fraction] = {
                "id": identifier,
                "deviations": _deviations(data["deviations"], f"{location}/deviations", parse),
            }
            if "score" in data:
                score_path = f"{location}/score"
                if not has_objective:
                    _invalid("input.invalid_reference", "The score has no declared objective.",
                             "Declare the objective basis and unit or omit the score.", score_path)
                score = _object(data["score"], score_path, ("value",), ("source_ref",))
                item["score"] = {"value": parse_decimal_text(score["value"], f"{score_path}/value")}
                if "source_ref" in score:
                    item["score"]["source_ref"] = _text(score["source_ref"], f"{score_path}/source_ref")
            options.append(item)
        groups.append({"callout": callout, "options": options})
    return groups


def _parse_common(
    data: dict[str, object], path: str, parse_length: _ScalarParser, parse_temp: _ScalarParser,
) -> ResolvedProblem[Fraction]:
    _choice(data["scope"], f"{path}/scope", "single_chain")
    problem: ResolvedProblem[Fraction] = {
        "scope": "single_chain",
        "chain": _chain(data["chain"], f"{path}/chain"),
        "requirement": parse_requirement(data["requirement"], parse_length, path=f"{path}/requirement"),
        "model": _model(data["model"], f"{path}/model", parse_temp),
        "dimensions": [],
        "option_groups": _option_groups(data.get("option_groups", []), f"{path}/option_groups",
                                        parse_length, has_objective="objective" in data),
    }
    _text(problem["requirement"]["id"], f"{path}/requirement/id")
    if "objective" in data:
        problem["objective"] = _objective(data["objective"], f"{path}/objective")
    return problem


def _check_references(
    problem: ResolvedProblem[Fraction], callouts: dict[str, _CalloutKey], path: str,
) -> None:
    active: set[_CalloutKey] = set()
    for index, term in enumerate(problem["chain"]["terms"]):
        identifier = term["logical_id"]
        if identifier not in callouts:
            _invalid("input.invalid_reference", "The chain references an undeclared dimension.",
                     "Use a declared logical ID.", f"{path}/chain/terms/{index}/logical_id")
        active.add(callouts[identifier])
    for index, group in enumerate(problem["option_groups"]):
        if callout_key(group["callout"]) not in active:
            _invalid("input.invalid_reference", "The option group references a callout outside the chain.",
                     "Use the exact identity of a callout in the chain.", f"{path}/option_groups/{index}/callout")


def _check_option_limits(
    problem: ResolvedProblem[Fraction], nominal_by_callout: dict[_CalloutKey, Fraction], path: str,
) -> None:
    for group_index, group in enumerate(problem["option_groups"]):
        nominal = nominal_by_callout.get(callout_key(group["callout"]))
        if nominal is None:
            continue
        for option_index, option in enumerate(group["options"]):
            pointer = f"{path}/option_groups/{group_index}/options/{option_index}/deviations/lower"
            _drawing_limits(nominal, option["deviations"], pointer)


def _native_target(data: dict[str, object], path: str) -> None:
    adapter = _choice(data["adapter"], f"{path}/adapter", "solidworks", "freecad")
    occurrence = f"{path}/occurrence_path"
    components = _array(data["occurrence_path"], occurrence, nonempty=True)
    for index, component in enumerate(components):
        _text(component, f"{occurrence}/{index}")
    _text(data["configuration"], f"{path}/configuration")
    _text(data["dimension_id"], f"{path}/dimension_id")
    if adapter == "freecad":
        if len(components) != 1:
            _invalid("input.invalid_value", "A FreeCAD target requires one document-local object name.",
                     "Use the object's internal Name as the sole path segment.", occurrence)
        _choice(data["configuration"], f"{path}/configuration", FREECAD_UNCONFIGURED)


def _dimension_spec(
    value: object, path: str, model: ThermalModel[Fraction],
) -> _DimensionInput:
    data = _object(value, path, ("logical_id", "physical_id", "callout", "alpha", "nominal", "tolerance"))
    _text(data["logical_id"], f"{path}/logical_id")
    _text(data["physical_id"], f"{path}/physical_id")
    _callout(data["callout"], f"{path}/callout")
    alpha, _ = _quantity(data["alpha"], f"{path}/alpha", ("1/K",))
    _check_alpha(alpha, model, f"{path}/alpha")

    nominal_path = f"{path}/nominal"
    nominal = None
    if _tag(data["nominal"], nominal_path, "kind", "manual", "cad") == "manual":
        manual = _object(data["nominal"], nominal_path, ("kind", "length", "source_ref"))
        _text(manual["source_ref"], f"{nominal_path}/source_ref")
        length_path = f"{nominal_path}/length"
        nominal = _nonnegative_length(_length(manual["length"], length_path), length_path)
    else:
        cad = _object(data["nominal"], nominal_path, ("kind", "target"))
        target_path = f"{nominal_path}/target"
        target = _object(cad["target"], target_path, ("adapter", "occurrence_path", "configuration", "dimension_id"))
        _native_target(target, target_path)

    tol_path = f"{path}/tolerance"
    deviations = None
    if _tag(data["tolerance"], tol_path, "kind", "manual", "cad") == "manual":
        tolerance = _object(data["tolerance"], tol_path, ("kind", "deviations", "source_ref"))
        _text(tolerance["source_ref"], f"{tol_path}/source_ref")
        deviations = _deviations(tolerance["deviations"], f"{tol_path}/deviations", _length)
        if nominal is not None:
            _drawing_limits(nominal, deviations, f"{tol_path}/deviations/lower")
    else:
        _object(data["tolerance"], tol_path, ("kind",))
        if nominal is not None:
            _invalid("input.invalid_operation", "A manual nominal requires a manual tolerance.",
                     "Declare manual deviations and their source.", f"{tol_path}/kind")
    return _DimensionInput(cast(DimensionSpec, data), alpha, nominal, deviations)


def _check_identities(
    dimensions: Iterable[_DimensionValues], path: str,
) -> dict[_CalloutKey, Fraction]:
    """Check known values even when some CAD measurements are still pending."""
    physical: dict[str, tuple[_CalloutKey, Fraction]] = {}
    physical_nominals: dict[str, Fraction] = {}
    callout_deviations: dict[_CalloutKey, Deviations[Fraction]] = {}
    minimum_nominals: dict[_CalloutKey, Fraction] = {}
    for index, (physical_id, reference, alpha, nominal, deviations) in enumerate(dimensions):
        pointer = f"{path}/dimensions/{index}"
        callout = callout_key(reference)
        definition = (callout, alpha)
        if physical.setdefault(physical_id, definition) != definition:
            _identity_error(f"{pointer}/physical_id", "Physical aliases disagree on the callout or coefficient.")
        if nominal is not None:
            if physical_nominals.setdefault(physical_id, nominal) != nominal:
                _identity_error(f"{pointer}/physical_id", "Physical aliases disagree on the nominal length.")
            minimum_nominals[callout] = min(nominal, minimum_nominals.get(callout, nominal))
        if deviations is not None:
            if callout_deviations.setdefault(callout, deviations) != deviations:
                _identity_error(f"{pointer}/callout", "A shared callout has conflicting baseline deviations.")
    return minimum_nominals


def _check_resolved_identities(problem: ResolvedProblem[Fraction], path: str) -> None:
    values = (
        (item["physical_id"], item["callout"], item["alpha"], item["nominal"],
         item["drawing_limits"]["deviations"])
        for item in problem["dimensions"]
    )
    _check_option_limits(problem, _check_identities(values, path), path)


def _parse_case(value: object, path: str = "") -> _CaseInput:
    validate_header(value, "case", path=path)
    data = _object(value, path,
                   ("kind", "schema_version", "case_id", "scope", "chain", "requirement", "model", "dimensions"),
                   ("option_groups", "objective"))
    _text(data["case_id"], f"{path}/case_id")
    common = _parse_common(data, path, _length, _temperature)
    dimensions: list[_DimensionInput] = []
    callouts: dict[str, _CalloutKey] = {}
    for index, fields in enumerate(_array(data["dimensions"], f"{path}/dimensions", nonempty=True)):
        pointer = f"{path}/dimensions/{index}"
        item = _dimension_spec(fields, pointer, common["model"])
        identifier = item.spec["logical_id"]
        if identifier in callouts:
            _duplicate(f"{pointer}/logical_id")
        callouts[identifier] = callout_key(item.spec["callout"])
        dimensions.append(item)
    _check_references(common, callouts, path)
    values = (
        (item.spec["physical_id"], item.spec["callout"], item.alpha, item.nominal, item.deviations)
        for item in dimensions
    )
    _check_option_limits(common, _check_identities(values, path), path)
    return _CaseInput(cast(CaseDocument, data), common, dimensions)


def _load_json(path: Path) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate object key {key!r}.")
            result[key] = value
        return result

    def reject_constant(token: str) -> NoReturn:
        raise ValueError(f"{token} is outside the JSON grammar.")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError(
            {"code": "io.read_failed", "severity": "error", "message": f"Could not read {path}: {exc}",
             "recovery": "Check that the input file exists and is readable.", "source_ref": str(path)},
            ExitStatus.INVALID_INPUT,
        ) from exc
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ContractError(
            {"code": "input.malformed_json", "severity": "error", "message": f"Invalid JSON: {exc}",
             "recovery": "Supply a UTF-8 JSON document with unique keys.", "source_ref": str(path)},
            ExitStatus.INVALID_INPUT,
        ) from exc


def load_case(path: Path) -> CaseDocument:
    """Read and validate an authored case before opening a CAD session."""
    return _parse_case(_load_json(path)).document


def load_extraction_records(path: Path) -> list[object]:
    """Read an exported record array. The resolver validates its items against the case."""
    return _array(_load_json(path), "/extraction_records")


def _bindings(case: _CaseInput) -> list[CadBinding]:
    return [
        {"logical_id": item.spec["logical_id"], "target": item.spec["nominal"]["target"]}
        for item in case.dimensions if item.spec["nominal"]["kind"] == "cad"
    ]


def cad_bindings(case: CaseDocument, *, adapter: str) -> list[CadBinding]:
    """Prepare a validated, ordered binding list for the selected adapter."""
    inputs = _parse_case(case)
    bindings = _bindings(inputs)
    if not bindings:
        _invalid("input.invalid_operation", "Extraction requires at least one CAD nominal.",
                 "Analyze or allocate the manual case directly.", "/dimensions")
    for index, item in enumerate(inputs.dimensions):
        nominal = item.spec["nominal"]
        if nominal["kind"] == "cad" and nominal["target"]["adapter"] != adapter:
            _invalid("input.invalid_operation", "The binding targets a different adapter.",
                     "Select the case's declared adapter.", f"/dimensions/{index}/nominal/target/adapter")
    return deepcopy(bindings)


def _diagnostic(value: object, path: str) -> Diagnostic:
    data = _object(value, path, ("code", "severity", "message", "recovery"),
                   ("field", "logical_id", "source_ref"))
    _choice(data["code"], f"{path}/code", *get_args(DiagnosticCode))
    _choice(data["severity"], f"{path}/severity", "warning", "error")
    for key in ("message", "recovery", "logical_id", "source_ref"):
        if key in data:
            _text(data[key], f"{path}/{key}")
    if "field" in data:
        field = data["field"]
        # The empty pointer denotes the whole document.
        if not isinstance(field, str) or (field and not field.startswith("/")):
            _invalid("input.invalid_value", "The diagnostic field is not a JSON Pointer.",
                     "Supply a JSON Pointer or omit the field.", f"{path}/field")
        if field:
            _text(field, f"{path}/field")
            if any("~" in token.replace("~0", "").replace("~1", "") for token in field.split("/")):
                _invalid("input.invalid_value", "The diagnostic pointer has an invalid escape.",
                         "Escape literal tilde and slash as ~0 and ~1.", f"{path}/field")
    return cast(Diagnostic, data.copy())


def _diagnostics(value: object, path: str) -> list[Diagnostic]:
    return [_diagnostic(item, f"{path}/{index}") for index, item in enumerate(_array(value, path))]


def _cad_source(value: object, path: str) -> CadSource:
    data = _object(value, path, (
        "adapter", "application", "application_version", "assembly", "assembly_configuration",
        "occurrence_path", "document", "configuration", "dimension_id",
    ))
    _native_target(data, path)
    for key in ("application", "application_version", "assembly_configuration"):
        _text(data[key], f"{path}/{key}")
    for key in ("assembly", "document"):
        pointer = f"{path}/{key}"
        document = _object(data[key], pointer, ("id", "state"), ("path",))
        _text(document["id"], f"{pointer}/id")
        _choice(document["state"], f"{pointer}/state", "saved", "modified", "unsaved", "unknown")
        if "path" in document:
            _text(document["path"], f"{pointer}/path")
    if data["adapter"] == "freecad":
        _choice(data["assembly_configuration"], f"{path}/assembly_configuration", FREECAD_UNCONFIGURED)
        if data["assembly"] != data["document"]:
            _identity_error(f"{path}/document", "The FreeCAD source must be in the same document.")
    return cast(CadSource, data)


def _observed_key(source: CadSource) -> tuple[str, str, str, tuple[str, ...], str, str, str]:
    return (
        source["adapter"], source["assembly"]["id"], source["assembly_configuration"],
        tuple(source["occurrence_path"]), source["document"]["id"],
        source["configuration"], source["dimension_id"],
    )


def _cad_tolerance(value: object, path: str) -> Deviations[Fraction] | None:
    status = _tag(value, path, "status", "supported", "missing", "unsupported", "drawing_only", "unavailable")
    required = ("status", "deviations") if status == "supported" else ("status",)
    data = _object(value, path, required, ("native_type", "native_status"))
    if "native_type" in data and type(data["native_type"]) is not int:
        _text(data["native_type"], f"{path}/native_type")
    if "native_status" in data:
        statuses = data["native_status"]
        if not isinstance(statuses, dict):
            _invalid("input.type", "Expected native status codes by read name.",
                     "Supply a JSON object or omit native_status.", f"{path}/native_status")
        for key, token in statuses.items():
            location = _pointer(f"{path}/native_status", key)
            _text(key, location)
            if type(token) is not int:
                _text(token, location)
    if status == "supported":
        return _deviations(data["deviations"], f"{path}/deviations", _length)
    return None


def _tolerance_error(item: _DimensionInput, index: int, path: str = "") -> Diagnostic:
    return {
        "code": "cad.tolerance_unresolved",
        "severity": "error",
        "message": "The selected CAD tolerance has no supported deviations.",
        "recovery": "Declare a sourced manual tolerance or use qualified CAD tolerance evidence.",
        "field": f"{path}/dimensions/{index}/tolerance",
        "logical_id": item.spec["logical_id"],
    }


def _read_observations(
    case: _CaseInput, records: Sequence[object], path: str, *, replay: bool = False,
) -> dict[str, _Observation]:
    bound = {
        item.spec["logical_id"]: (index, item) for index, item in enumerate(case.dimensions)
        if item.spec["nominal"]["kind"] == "cad"
    }
    seen: set[str] = set()
    observations: dict[str, _Observation] = {}
    reported: dict[str, list[Diagnostic]] = {}
    physical_by_observed = {}
    observed_by_physical = {}
    freecad_document: CadDocumentRef | None = None
    for index, record in enumerate(records):
        pointer = f"{path}/{index}"
        validate_header(record, "cad_extraction", path=pointer)
        status = _tag(record, pointer, "status", "resolved", "failed")
        required = ("kind", "schema_version", "status", "logical_id", "diagnostics")
        if status == "resolved":
            data = _object(record, pointer, (*required, "source", "nominal", "tolerance"))
        else:
            data = _object(record, pointer, required, ("source",))
        identifier = _text(data["logical_id"], f"{pointer}/logical_id")
        if identifier in seen:
            _duplicate(f"{pointer}/logical_id")
        if identifier not in bound:
            _invalid("input.invalid_reference", "The record has no requested binding.",
                     "Supply exactly one record per CAD binding.", f"{pointer}/logical_id")
        seen.add(identifier)
        diagnostics = _diagnostics(data["diagnostics"], f"{pointer}/diagnostics")
        for diag_index, item in enumerate(diagnostics):
            if item.get("logical_id", identifier) != identifier:
                _identity_error(f"{pointer}/diagnostics/{diag_index}/logical_id",
                                "The diagnostic names a different binding.")
        has_error = any(item["severity"] == "error" for item in diagnostics)
        reported[identifier] = [{**item, "logical_id": identifier} for item in diagnostics]
        if status == "failed":
            if replay:
                _invalid("input.invalid_value", "A snapshot contains a failed extraction record.",
                         "Supply a complete resolved snapshot.", f"{pointer}/status")
            if not has_error:
                _invalid("input.required", "The failed binding is missing an error diagnostic.",
                         "Return an error diagnostic for each failed binding.", f"{pointer}/diagnostics")
            if "source" in data:
                _cad_source(data["source"], f"{pointer}/source")
            continue
        if has_error:
            _invalid("input.invalid_value", "A resolved record has an error diagnostic.",
                     "Return an error only with a failed binding.", f"{pointer}/diagnostics")
        source = _cad_source(data["source"], f"{pointer}/source")
        spec_index, item = bound[identifier]
        spec = item.spec
        nominal_spec = spec["nominal"]
        if nominal_spec["kind"] != "cad":
            _internal("A bound record refers to a manual nominal.")
        for key, requested in nominal_spec["target"].items():
            if source[key] != requested:
                _identity_error(f"{pointer}/source/{key}", "The observation does not match the requested target.")
        observed = _observed_key(source)
        physical = spec["physical_id"]
        if physical_by_observed.setdefault(observed, physical) != physical:
            _identity_error(f"{pointer}/source", "One CAD observation maps to multiple physical IDs.")
        if observed_by_physical.setdefault(physical, observed) != observed:
            _identity_error(f"{pointer}/source", "Physical aliases point to different CAD observations.")
        nominal_path = f"{pointer}/nominal"
        nominal = _nonnegative_length(_length(data["nominal"], nominal_path), nominal_path)
        deviations = _cad_tolerance(data["tolerance"], f"{pointer}/tolerance")
        if source["adapter"] == "freecad":
            if freecad_document is None:
                freecad_document = source["document"]
            elif freecad_document != source["document"]:
                _identity_error(f"{pointer}/source/document", "A FreeCAD record batch must use one document.")
            if deviations is not None:
                _invalid("input.invalid_value", "FreeCAD does not supply qualified native tolerances.",
                         "Declare sourced manual deviations in the case.", f"{pointer}/tolerance")
        if deviations is None and not diagnostics:
            _invalid("input.required", "Unresolved CAD tolerance evidence requires a warning.",
                     "Return a warning explaining the tolerance status.", f"{pointer}/diagnostics")
        if not replay and deviations is None and spec["tolerance"]["kind"] == "cad":
            reported[identifier].append(_tolerance_error(item, spec_index))
        observations[identifier] = _Observation(cast(CadExtractionSuccess, data), nominal, deviations)
    missing = bound.keys() - seen
    if missing:
        _invalid("input.required", f"No extraction record for {', '.join(sorted(missing))}.",
                 "Supply exactly one record per CAD binding.", path)
    diagnostics = [item for identifier in bound for item in reported[identifier]]
    if any(item["severity"] == "error" for item in diagnostics):
        raise ExtractionError(diagnostics)
    return observations


def _resolve_observations(case: _CaseInput, records: Sequence[object]) -> dict[str, _Observation]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ExtractionError([{
            "code": "cad.protocol_error", "severity": "error",
            "message": "The adapter did not return a sequence of binding records.",
            "recovery": "Check the adapter's v1 output contract.", "field": "/extraction_records",
        }])
    try:
        return _read_observations(case, records, "/extraction_records")
    except ExtractionError:
        raise
    except ContractError as exc:
        raise ExtractionError([{
            **exc.diagnostic,
            "code": "cad.protocol_error",
            "recovery": "Check the adapter's v1 output contract and requested binding identities.",
        }]) from exc


def _source_warnings(source: CadSource, identifier: str) -> list[Diagnostic]:
    warnings: list[Diagnostic] = []
    for role in ("assembly", "document"):
        document = source[role]
        if document["state"] != "saved":
            warnings.append({
                "code": "cad.source_state", "severity": "warning",
                "message": f"Observed CAD {role} state was {document['state']}.",
                "recovery": "Check the observed document state when comparing or repeating extraction.",
                "logical_id": identifier, "source_ref": document.get("path", document["id"]),
            })
    return warnings


def resolve_case(
    case: CaseDocument, extraction_records: Sequence[object] | None = None,
) -> ResolvedCase:
    """Join a validated case and its records, producing exact normalized inputs."""
    inputs = _parse_case(case)
    if extraction_records is None and _bindings(inputs):
        _invalid("input.invalid_operation", "The case contains CAD nominals.",
                 "Extract a snapshot before offline analysis or allocation.", "/dimensions")
    observations = _resolve_observations(inputs, extraction_records if extraction_records is not None else ())

    diagnostics: list[Diagnostic] = []
    dimensions: list[ResolvedDimension[Fraction]] = []
    for index, item in enumerate(inputs.dimensions):
        spec = item.spec
        identifier = spec["logical_id"]
        nominal, deviations = item.nominal, item.deviations
        observation = observations.get(identifier)
        if observation is not None:
            nominal = observation.nominal
            diagnostics.extend(observation.record["diagnostics"])
            diagnostics.extend(_source_warnings(observation.record["source"], identifier))
            if deviations is None:
                deviations = observation.deviations
            elif observation.deviations is not None and deviations != observation.deviations:
                tolerance = spec["tolerance"]
                if tolerance["kind"] != "manual":
                    _internal("CAD deviations were compared with a non-manual tolerance.")
                diagnostics.append({
                    "code": "cad.tolerance_discrepancy", "severity": "warning",
                    "message": "The selected manual deviations differ from the extracted CAD deviations.",
                    "recovery": "Verify that the declared manual source is the intended authority.",
                    "field": f"/dimensions/{index}/tolerance", "logical_id": identifier,
                    "source_ref": tolerance["source_ref"],
                })
        if nominal is None or deviations is None:
            _internal(f"Dimension {identifier!r} was not fully resolved.")
        dimensions.append({
            "logical_id": identifier, "physical_id": spec["physical_id"],
            "callout": spec["callout"], "alpha": item.alpha, "nominal": nominal,
            "drawing_limits": _drawing_limits(nominal, deviations, f"/dimensions/{index}/tolerance"),
            "tolerance_source": spec["tolerance"]["kind"],
        })
    problem = inputs.common
    problem["dimensions"] = dimensions
    _check_resolved_identities(problem, "")
    records = [observations[item.spec["logical_id"]].record for item in inputs.dimensions
               if item.spec["logical_id"] in observations]
    return ResolvedCase(deepcopy(inputs.document), deepcopy(problem), deepcopy(records), deepcopy(diagnostics))
