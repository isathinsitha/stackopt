"""Export explicitly bound lengths from an active FreeCAD document."""

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any

from ..case import cad_bindings, load_case
from ..contract_validation import cad_double_to_decimal_text
from ..contracts import (
    FREECAD_UNCONFIGURED,
    SCHEMA_VERSION,
    CadBinding,
    CadDocumentRef,
    CadExtractionFailure,
    CadExtractionRecord,
    CadSource,
)
from ..diagnostics import ContractError, DiagnosticCode, ExitStatus
from ..snapshot import write_utf8_atomic


def _failed(
    binding: CadBinding, code: DiagnosticCode, message: str, recovery: str,
    *, source: CadSource | None = None,
) -> CadExtractionFailure:
    logical_id = binding["logical_id"]
    record: CadExtractionFailure = {
        "kind": "cad_extraction", "schema_version": SCHEMA_VERSION,
        "logical_id": logical_id, "status": "failed",
        "diagnostics": [{
            "code": code, "severity": "error", "logical_id": logical_id,
            "message": message, "recovery": recovery,
        }],
    }
    if source is not None:
        record["source"] = source
    return record


def _read_length(
    document: Any, binding: CadBinding, reference: CadDocumentRef, version: str,
) -> CadExtractionRecord:
    target = binding["target"]
    object_name, = target["occurrence_path"]
    property_name = target["dimension_id"]
    obj = document.getObject(object_name)
    if obj is None or property_name not in obj.PropertiesList:
        return _failed(binding, "cad.binding_missing", f"FreeCAD did not find {object_name}.{property_name}.",
                       "Check the internal object Name and the exact property name.")
    if obj.TypeId != "Part::Cylinder" or not obj.isValid():
        return _failed(binding, "cad.binding_unavailable", f"FreeCAD cannot read {object_name} in the qualified scope.",
                       "Use a valid native Part::Cylinder in the active document.")

    source: CadSource = {
        "adapter": "freecad", "application": "FreeCAD", "application_version": version,
        "assembly": reference.copy(), "assembly_configuration": FREECAD_UNCONFIGURED,
        "occurrence_path": [obj.Name], "document": reference.copy(),
        "configuration": FREECAD_UNCONFIGURED, "dimension_id": property_name,
    }
    try:
        if obj.getTypeIdOfProperty(property_name) != "App::PropertyLength":
            raise ValueError("The property is not an App::PropertyLength.")
        length = getattr(obj, property_name).getValueAs("mm").Value
        value = cad_double_to_decimal_text(length)
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        return _failed(binding, "cad.read_failed", f"Cannot read {object_name}.{property_name} as a length: {exc}",
                       "Bind an App::PropertyLength on the qualified object.", source=source)

    logical_id = binding["logical_id"]
    return {
        "kind": "cad_extraction", "schema_version": SCHEMA_VERSION,
        "logical_id": logical_id, "status": "resolved", "source": source,
        "nominal": {"value": value, "unit": "mm"}, "tolerance": {"status": "unavailable"},
        "diagnostics": [{
            "code": "cad.tolerance_unresolved", "severity": "warning", "logical_id": logical_id,
            "message": "The FreeCAD exporter reads nominal lengths only.",
            "recovery": "Declare explicit sourced manual deviations in the case.",
        }],
    }


def extract_active(bindings: Sequence[CadBinding], /) -> list[CadExtractionRecord]:
    """Read validated bindings inside FreeCAD without modifying the active model."""
    try:
        import FreeCAD
    except ImportError as exc:
        raise ContractError({
            "code": "cad.unavailable", "severity": "error",
            "message": "The FreeCAD Python API is unavailable in this interpreter.",
            "recovery": "Run the exporter inside FreeCAD's Python runtime.",
        }, ExitStatus.CAD_UNAVAILABLE) from exc

    document = FreeCAD.ActiveDocument
    if document is None or not document.FileName or document.mustExecute():
        raise ContractError({
            "code": "cad.session_invalid", "severity": "error",
            "message": "FreeCAD requires an active, file-backed document with no pending recompute.",
            "recovery": "Open the intended FCStd document and recompute it in FreeCAD before exporting.",
        }, ExitStatus.EXTRACTION_FAILED)

    path = Path(document.FileName).resolve()
    if path.suffix.lower() != ".fcstd" or not path.is_file():
        raise ContractError({
            "code": "cad.session_invalid", "severity": "error",
            "message": "The active document does not reference an existing FCStd file.",
            "recovery": "Open the intended native FCStd file.",
        }, ExitStatus.EXTRACTION_FAILED)

    # FreeCAD's isSaved() reports a file name, and isTouched() reports pending
    # recompute. Neither establishes whether a recomputed edit has been saved.
    reference: CadDocumentRef = {"id": str(path), "path": str(path), "state": "unknown"}
    version = ".".join(FreeCAD.Version()[:3])
    return [_read_length(document, binding, reference, version) for binding in bindings]


def export_active(case: Path, records_out: Path) -> None:
    """Validate a bound case and write its active-document observations as a JSON array."""
    destination = records_out.resolve()
    if destination.suffix.lower() != ".json" or destination == case.resolve():
        raise ContractError({
            "code": "input.invalid_operation", "severity": "error",
            "message": "The FreeCAD export requires a separate JSON output file.",
            "recovery": "Choose a .json destination distinct from the authored case.",
        }, ExitStatus.INVALID_INPUT)
    bindings = cad_bindings(load_case(case), adapter="freecad")
    write_utf8_atomic(destination, json.dumps(extract_active(bindings), indent=2, ensure_ascii=False) + "\n")
