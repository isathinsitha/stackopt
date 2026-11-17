"""Shared v1 validation and exact scalar conversion primitives."""

import math
import re
from collections.abc import Callable
from decimal import Decimal
from fractions import Fraction
from typing import Literal, NoReturn

from .contracts import SCHEMA_VERSION, Requirement
from .diagnostics import ContractError, DiagnosticCode, ExitStatus

_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
DocumentKind = Literal[
    "case", "snapshot", "cad_extraction", "analysis_result", "allocation_result",
    "diagnostic_result",
]


def _invalid(code: DiagnosticCode, message: str, recovery: str, path: str) -> NoReturn:
    raise ContractError(
        {"code": code, "severity": "error", "message": message, "recovery": recovery,
         "field": path},
        ExitStatus.INVALID_INPUT,
    )


def validate_header(
    data: object,
    kind: DocumentKind,
    *also: DocumentKind,
    path: str = "",
) -> DocumentKind:
    """Check kind and exact version before interpreting any document fields."""
    if not isinstance(data, dict):
        _invalid("input.type", "A document must be an object.", "Supply a JSON object.", path)
    for expected_kind in (kind, *also):
        if data.get("kind") == expected_kind:
            break
    else:
        expected = ", ".join((kind, *also))
        _invalid("input.kind", "Missing or unexpected document kind.", f"Use {expected}.", f"{path}/kind")
    version = data.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        _invalid("input.schema_version", "Unsupported or missing schema version.",
                 f"Supply an integer schema_version of {SCHEMA_VERSION}.", f"{path}/schema_version")
    return expected_kind


def parse_decimal_text(value: object, path: str) -> Fraction:
    """Parse a v1 decimal string exactly, independently of the Decimal context."""
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        _invalid("input.invalid_decimal", "Expected a finite fixed-point decimal string.",
                 'Use a quoted decimal such as "0.001".', path)
    return Fraction(Decimal(value))


def format_decimal_text(value: Fraction) -> str:
    """Write an exact finite decimal. Fail if the result would require rounding."""
    denominator = value.denominator
    twos = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    fives = 0
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("The value has no finite decimal representation.")

    places = max(twos, fives)
    if places == 0:
        return format(Decimal(value.numerator), "f")

    magnitude = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
    digits = format(Decimal(magnitude), "f").zfill(places + 1)
    sign = "-" if value < 0 else ""
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def cad_double_to_decimal_text(value: float) -> str:
    """Expand the shortest round-trip text for a finite CAD double to fixed point."""
    if not math.isfinite(value):
        raise ValueError("The CAD double must be finite.")
    return format(Decimal(repr(value)), "f")


def parse_requirement(
    value: object,
    parse_limit: Callable[[object, str], Fraction],
    *,
    path: str = "/requirement",
) -> Requirement[Fraction]:
    """Validate declared sides after the caller's exact length conversion."""
    if not isinstance(value, dict):
        _invalid("input.type", "A requirement must be an object.",
                 "Supply an ID and at least one clearance limit.", path)
    for key in value:
        if key not in {"id", "minimum", "maximum"}:
            token = str(key).replace("~", "~0").replace("/", "~1")
            _invalid("input.unknown_field", "Unknown requirement field.",
                     "Use id, minimum and maximum.", f"{path}/{token}")
    if "id" not in value:
        _invalid("input.required", "The requirement ID is missing.",
                 "Supply a nonblank requirement ID.", f"{path}/id")
    identifier = value["id"]
    if not isinstance(identifier, str) or not identifier.strip():
        _invalid("input.invalid_value", "The requirement ID must be a nonblank string.",
                 "Supply a nonblank requirement ID.", f"{path}/id")
    if "minimum" not in value and "maximum" not in value:
        _invalid("input.requirement_missing_limits", "No clearance limits were declared.",
                 "Declare minimum, maximum or both.", path)
    requirement: Requirement[Fraction] = {"id": identifier}
    if "minimum" in value:
        requirement["minimum"] = parse_limit(value["minimum"], f"{path}/minimum")
    if "maximum" in value:
        requirement["maximum"] = parse_limit(value["maximum"], f"{path}/maximum")
    if "minimum" in requirement and "maximum" in requirement:
        if requirement["minimum"] > requirement["maximum"]:
            _invalid("input.reversed_interval", "The maximum clearance is below the minimum.",
                     "Set the maximum at or above the minimum.", f"{path}/maximum")
    return requirement
