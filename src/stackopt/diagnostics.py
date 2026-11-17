"""Stable diagnostic vocabulary and command exit statuses."""

from enum import IntEnum
from typing import Literal, NotRequired, TypedDict


class ExitStatus(IntEnum):
    SUCCESS = 0
    EXECUTION_FAILURE = 1
    USAGE_ERROR = 2
    INVALID_INPUT = 3
    CAD_UNAVAILABLE = 4
    EXTRACTION_FAILED = 5
    ALLOCATION_INFEASIBLE = 6
    ALLOCATION_INCOMPLETE = 7


DiagnosticCode = Literal[
    "input.malformed_json",
    "input.required",
    "input.type",
    "input.unknown_field",
    "input.kind",
    "input.schema_version",
    "input.invalid_decimal",
    "input.unsupported_unit",
    "input.requirement_missing_limits",
    "input.reversed_interval",
    "input.duplicate_id",
    "input.invalid_reference",
    "input.conflicting_identity",
    "input.invalid_model",
    "input.invalid_operation",
    "input.invalid_value",
    "cad.unavailable",
    "cad.session_invalid",
    "cad.binding_missing",
    "cad.binding_ambiguous",
    "cad.binding_unavailable",
    "cad.read_failed",
    "cad.protocol_error",
    "cad.tolerance_unresolved",
    "cad.tolerance_discrepancy",
    "cad.source_state",
    "search.incomplete",
    "io.read_failed",
    "io.write_failed",
    "internal.failure",
]


class Diagnostic(TypedDict):
    code: DiagnosticCode
    severity: Literal["error", "warning"]
    message: str
    recovery: str
    field: NotRequired[str]
    logical_id: NotRequired[str]
    source_ref: NotRequired[str]


class DiagnosticResult(TypedDict):
    kind: Literal["diagnostic_result"]
    schema_version: Literal[1]
    command: Literal["extract", "analyze", "allocate"]
    diagnostics: list[Diagnostic]


class ContractError(Exception):
    """Expected boundary failure with one machine-readable diagnostic."""

    def __init__(self, diagnostic: Diagnostic, exit_status: ExitStatus):
        super().__init__(diagnostic["message"])
        self.diagnostic = diagnostic
        self.exit_status = exit_status
