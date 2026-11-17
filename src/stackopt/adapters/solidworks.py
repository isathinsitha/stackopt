"""Read named part dimensions from the active SOLIDWORKS assembly."""

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
import sys
from typing import Any

from ..contract_validation import cad_double_to_decimal_text
from ..contracts import (
    SCHEMA_VERSION,
    CadBinding,
    CadDocumentRef,
    CadExtractionFailure,
    CadExtractionRecord,
    CadSource,
    Length,
    SupportedCadTolerance,
    UnresolvedCadTolerance,
)
from ..diagnostics import ContractError, Diagnostic, DiagnosticCode, ExitStatus

_ASSEMBLY = 2  # swDocASSEMBLY
_PART = 1  # swDocPART
_RESOLVED = {2, 3}  # swComponentFullyResolved, swComponentResolved
_SPECIFY_CONFIGURATION = 3  # swSpecifyConfiguration
_LINEAR = 0  # swDimensionParamTypeDoubleLinear
_DRIVING = 2  # swDimensionDriving
_BILATERAL_AND_LIMIT = {2, 3}
_SYMMETRIC = 4


class _Session:
    def __init__(self, app: Any, pythoncom: Any, client: Any):
        self.pythoncom = pythoncom
        self.client = client
        self.com_error = pythoncom.com_error
        # GetActiveObject can attach even when this install's objects do not
        # expose GetTypeInfo. The installed library resolves the typed getters.
        library_path = Path(app.GetExecutablePath()) / "sldworks.tlb"
        library = pythoncom.LoadTypeLib(str(library_path))
        guid, lcid, _, major, minor, _ = library.GetLibAttr()
        self.types = client.gencache.EnsureModule(guid, lcid, major, minor)
        self.app = self.wrap("ISldWorks", app)

    def wrap(self, interface: str, obj: Any) -> Any:
        if obj is None:
            return None
        return getattr(self.types, interface)(obj._oleobj_)

    def configuration_names(self, name: str) -> Any:
        # A Python tuple marshals as a VARIANT array. The read needs BSTRs.
        return self.client.VARIANT(self.pythoncom.VT_ARRAY | self.pythoncom.VT_BSTR, (name,))

    def active_configuration(self, model: Any) -> Any:
        manager = self.wrap("IConfigurationManager", model.ConfigurationManager)
        return self.wrap("IConfiguration", manager.ActiveConfiguration) if manager else None


def _unavailable(message: str, recovery: str) -> ContractError:
    return ContractError(
        {"code": "cad.unavailable", "severity": "error", "message": message, "recovery": recovery},
        ExitStatus.CAD_UNAVAILABLE,
    )


def extract_active(bindings: Sequence[CadBinding], /) -> list[CadExtractionRecord]:
    """Extract one v1 outcome per validated binding on the CLI thread."""
    if not bindings:
        return []
    if sys.platform != "win32":
        raise _unavailable("SOLIDWORKS extraction requires Windows.",
                           "Run extract in the Windows SOLIDWORKS desktop session.")
    try:
        import pythoncom
        import win32com.client
    except (ImportError, OSError) as exc:
        raise _unavailable("The optional pywin32 dependency could not be loaded.",
                           "Install pywin32 in the Python environment used for extract.") from exc

    # pythoncom owns initialization of the main thread. Uninitializing here
    # would also disconnect the caller's existing COM objects on that thread.
    return _extract_windows(bindings, pythoncom, win32com.client)


def _extract_windows(bindings: Sequence[CadBinding], pythoncom: Any, client: Any) -> list[CadExtractionRecord]:
    try:
        app = client.GetActiveObject("SldWorks.Application")
    except pythoncom.com_error as exc:
        raise _unavailable("No accessible running SOLIDWORKS session was found.",
                           "Start SOLIDWORKS and run extract from the same Windows desktop.") from exc
    try:
        session = _Session(app, pythoncom, client)
    except (pythoncom.com_error, OSError, ImportError, AttributeError) as exc:
        raise _unavailable("The running SOLIDWORKS installation's COM types could not be loaded.",
                           "Check the installation's sldworks.tlb and the pywin32 type cache.") from exc
    return _read_assembly(session, bindings)


def _invalid_session(message: str) -> ContractError:
    return ContractError(
        {"code": "cad.session_invalid", "severity": "error", "message": message,
         "recovery": "Open the intended resolved assembly and make it the active SOLIDWORKS document."},
        ExitStatus.EXTRACTION_FAILED,
    )


def _read_assembly(session: _Session, bindings: Sequence[CadBinding]) -> list[CadExtractionRecord]:
    try:
        assembly = session.wrap("IModelDoc2", session.app.ActiveDoc)
        if assembly is None or assembly.GetType() != _ASSEMBLY:
            raise _invalid_session("The running session has no active assembly.")
        configuration = session.active_configuration(assembly)
        root = session.wrap("IComponent2", configuration.GetRootComponent3(False)) if configuration else None
        if root is None:
            raise _invalid_session("The active assembly has no accessible configuration root.")
        revision = session.app.RevisionNumber()
        assembly_config = configuration.Name
        assembly_ref = _document_ref(session, assembly)
        components = defaultdict(list)
        for child in root.GetChildren() or ():
            component = session.wrap("IComponent2", child)
            components[component.Name2].append(component)
    except session.com_error as exc:
        raise _invalid_session("SOLIDWORKS could not enumerate the active assembly.") from exc

    return [_read_binding(session, binding, components, revision, assembly_ref, assembly_config)
            for binding in bindings]


def _document_ref(session: _Session, model: Any) -> CadDocumentRef:
    try:
        path = model.GetPathName()
    except session.com_error:
        return {"id": "document:" + model.GetTitle(), "state": "unknown"}
    if not path:
        return {"id": "unsaved:" + model.GetTitle(), "state": "unsaved"}
    try:
        return {"id": path, "path": path, "state": "modified" if model.GetSaveFlag() else "saved"}
    except session.com_error:
        return {"id": path, "path": path, "state": "unknown"}


def _length(value: float) -> Length:
    return {"value": cad_double_to_decimal_text(value), "unit": "m"}


def _read_binding(
    session: _Session, binding: CadBinding, components: dict[str, list[Any]],
    revision: str, assembly_ref: CadDocumentRef, assembly_config: str,
) -> CadExtractionRecord:
    logical_id = binding["logical_id"]
    target = binding["target"]
    occurrence_path = target["occurrence_path"]
    dimension_id = target["dimension_id"]
    source: CadSource | None = None

    def fail(code: DiagnosticCode, message: str, recovery: str) -> CadExtractionFailure:
        failure: CadExtractionFailure = {
            "kind": "cad_extraction", "schema_version": SCHEMA_VERSION, "logical_id": logical_id,
            "status": "failed", "diagnostics": [
                {"code": code, "severity": "error", "logical_id": logical_id,
                 "message": message, "recovery": recovery},
            ],
        }
        if source is not None:
            failure["source"] = source
        return failure

    if target["adapter"] != "solidworks" or len(occurrence_path) != 1:
        return fail("cad.binding_unavailable", "Only top-level SOLIDWORKS occurrences are supported.",
                    "Bind one exact top-level occurrence with the solidworks adapter.")
    occurrence = occurrence_path[0]
    matches = components.get(occurrence, ())
    if not matches:
        return fail("cad.binding_missing", f"Occurrence {occurrence!r} was not found.",
                    "Check the active assembly configuration and exact occurrence name.")
    if len(matches) != 1:
        return fail("cad.binding_ambiguous", f"Several components matched occurrence {occurrence!r}.",
                    "Use a uniquely named occurrence in the active assembly configuration.")

    try:
        component = matches[0]
        state = component.GetSuppression2()
        if state not in _RESOLVED:
            condition = {0: "suppressed", 1: "lightweight", 4: "lightweight"}.get(state, "unavailable")
            return fail("cad.binding_unavailable", f"Occurrence {occurrence!r} is {condition} (state {state}).",
                        "Unsuppress and fully resolve the occurrence in SOLIDWORKS.")
        config = component.ReferencedConfiguration
        if config != target["configuration"]:
            return fail("cad.binding_unavailable",
                        f"Occurrence {occurrence!r} references {config!r}, expected {target['configuration']!r}.",
                        "Check the declared referenced configuration.")
        if component.IsVirtual:
            return fail("cad.binding_unavailable", f"Occurrence {occurrence!r} is virtual.",
                        "Use a resolved occurrence of an external native part document.")
        part = session.wrap("IModelDoc2", component.GetModelDoc2())
        if part is None or part.GetType() != _PART:
            return fail("cad.binding_unavailable", f"Occurrence {occurrence!r} has no loaded part document.",
                        "Resolve the intended native part in SOLIDWORKS.")
        if config not in (part.GetConfigurationNames() or ()):
            return fail("cad.binding_unavailable", f"Configuration {config!r} is absent from the part.",
                        "Check the component's referenced part and configuration.")

        dimension = session.wrap("IDimension", part.Parameter(dimension_id))
        # FullName adds the model name after the parameter@feature identifier.
        if dimension is None or dimension.FullName.rpartition("@")[0] != dimension_id:
            return fail("cad.binding_missing", f"Exact part dimension {dimension_id!r} was not found.",
                        "Use the exact parameter@feature identifier in the referenced part.")
        source = {
            "adapter": "solidworks", "application": "SOLIDWORKS", "application_version": revision,
            "assembly": assembly_ref.copy(), "assembly_configuration": assembly_config,
            "occurrence_path": [occurrence], "document": _document_ref(session, part),
            "configuration": config, "dimension_id": dimension_id,
        }
        if dimension.GetType() != _LINEAR:
            return fail("cad.read_failed", f"Dimension {dimension_id!r} is outside the supported linear type.",
                        "Bind a named native length or diameter dimension.")
        names = session.configuration_names(config)
        feature = session.wrap("IFeature", dimension.GetFeatureOwner())
        suppression = feature.IsSuppressed2(_SPECIFY_CONFIGURATION, names) if feature is not None else None
        if suppression != (False,):
            return fail("cad.binding_unavailable",
                        f"The owning feature of {dimension_id!r} is suppressed or unavailable in {config!r}.",
                        "Use an unsuppressed dimension in the referenced configuration.")
        values = dimension.GetSystemValue3(_SPECIFY_CONFIGURATION, names)
        if not values or len(values) != 1 or values[0] < 0:
            return fail("cad.read_failed", "The named-configuration read did not return one nonnegative length.",
                        "Check the dimension value and availability in the referenced configuration.")
        nominal = _length(values[0])
    except (session.com_error, TypeError, ValueError):
        return fail("cad.read_failed", f"SOLIDWORKS could not read {dimension_id!r} in {occurrence!r}.",
                    "Check the exact part dimension and occurrence configuration.")

    tolerance, reason = _read_tolerance(session, part, dimension, config)
    warnings: list[Diagnostic] = []
    if reason:
        warnings.append({
            "code": "cad.tolerance_unresolved", "severity": "warning", "logical_id": logical_id,
            "message": reason, "recovery": "Supply an explicit sourced tolerance in the case or use a qualified model tolerance.",
            "source_ref": source["document"]["id"],
        })
    return {
        "kind": "cad_extraction", "schema_version": SCHEMA_VERSION, "logical_id": logical_id,
        "status": "resolved", "source": source, "nominal": nominal,
        "tolerance": tolerance, "diagnostics": warnings,
    }


def _read_tolerance(
    session: _Session, part: Any, dimension: Any, referenced: str,
) -> tuple[SupportedCadTolerance | UnresolvedCadTolerance, str]:
    evidence: UnresolvedCadTolerance = {"status": "unavailable"}
    try:
        configuration = session.active_configuration(part)
        # The tolerance getters read the part's active configuration only.
        observed = configuration.Name if configuration is not None else None
        if observed != referenced:
            return evidence, f"Part active configuration {observed!r} differs from occurrence configuration {referenced!r}."
        if dimension.DrivenState != _DRIVING:
            evidence["status"] = "unsupported"
            return evidence, "Model tolerance reads are qualified for driving dimensions."
        tolerance = session.wrap("IDimensionTolerance", dimension.Tolerance)
        if tolerance is None:
            return evidence, "SOLIDWORKS returned no model tolerance object."
        native_type = evidence["native_type"] = tolerance.Type
        low_status, low = tolerance.GetMinValue2()
        statuses = {"GetMinValue2": low_status}
        evidence["native_status"] = statuses
        high_status, high = tolerance.GetMaxValue2()
        statuses["GetMaxValue2"] = high_status
        if native_type == 0:
            evidence["status"] = "missing"
            return evidence, "The dimension has no model tolerance."
        if native_type == _SYMMETRIC:
            if (low_status, high_status) != (1, 0) or high < 0:
                return evidence, "The symmetric model tolerance returned an invalid magnitude or status."
            low = -high
        elif native_type not in _BILATERAL_AND_LIMIT:
            evidence["status"] = "unsupported"
            return evidence, f"Model tolerance type {native_type} is outside the qualified types."
        elif (low_status, high_status) != (0, 0) or low > high:
            return evidence, "The model tolerance returned invalid signed offsets or statuses."
        return {"status": "supported", "native_type": native_type, "native_status": statuses,
                "deviations": {"lower": _length(low), "upper": _length(high)}}, ""
    except (session.com_error, TypeError, ValueError):
        return evidence, "SOLIDWORKS could not read valid model tolerance evidence."
