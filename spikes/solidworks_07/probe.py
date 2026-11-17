"""Chat 07 evidence probe. Reads the active SOLIDWORKS assembly without edits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pythoncom
from win32com.client import GetActiveObject, VARIANT, gencache

from stackopt.contract_validation import cad_double_to_decimal_text


DEFAULT_INSTALL = Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS")
RESOLVED = {2, 3}
BILATERAL_AND_LIMIT = {2, 3}
SYMMETRIC = 4


class Session:
    def __init__(self, install: Path):
        library = pythoncom.LoadTypeLib(str(install / "sldworks.tlb"))
        guid, lcid, _, major, minor, _ = library.GetLibAttr()
        self.types = gencache.EnsureModule(guid, lcid, major, minor)
        self.app = self.wrap("ISldWorks", GetActiveObject("SldWorks.Application"))

    def wrap(self, interface, obj):
        if obj is None:
            return None
        return getattr(self.types, interface)(obj._oleobj_)


def config_names(*names):
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, names)


def active_configuration(session, model):
    manager = session.wrap("IConfigurationManager", model.ConfigurationManager)
    return session.wrap("IConfiguration", manager.ActiveConfiguration)


def document_ref(model):
    path = model.GetPathName()
    if not path:
        return {"id": "unsaved:" + model.GetTitle(), "state": "unsaved"}
    try:
        state = "modified" if model.GetSaveFlag() else "saved"
    except pythoncom.com_error:
        state = "unknown"
    return {"id": path, "path": path, "state": state}


def length(value):
    return {"value": cad_double_to_decimal_text(float(value)), "unit": "m"}


def diagnostic(logical_id, code, message, recovery, *, severity="error"):
    return dict(code=code, severity=severity, logical_id=logical_id,
                message=message, recovery=recovery)


def top_components(session, assembly):
    root = active_configuration(session, assembly).GetRootComponent3(False)
    root = session.wrap("IComponent2", root)
    if root is None:
        raise RuntimeError("The active assembly configuration has no resolved root.")
    return [session.wrap("IComponent2", component) for component in root.GetChildren() or ()]


def read_tolerance(session, dimension, active_config, occurrence_config):
    tolerance = session.wrap("IDimensionTolerance", dimension.Tolerance)
    if tolerance is None:
        return {"status": "unavailable"}, {}, "COM returned no tolerance object."
    native_type = tolerance.Type
    low_status, low = tolerance.GetMinValue2()
    high_status, high = tolerance.GetMaxValue2()
    evidence = {
        "native_type": native_type,
        "native_status": {"GetMinValue2": low_status, "GetMaxValue2": high_status},
    }
    raw = {**evidence, "values": {"GetMinValue2": length(low), "GetMaxValue2": length(high)}}
    if active_config != occurrence_config:
        return {"status": "unavailable"}, raw, (
            "Tolerance calls have no configuration argument and the part's active "
            "configuration differs from the occurrence's referenced configuration."
        )
    if native_type == 0:
        return {**evidence, "status": "missing"}, raw, "No model tolerance is set."
    if native_type == SYMMETRIC:
        if (low_status, high_status) != (1, 0) or high < 0:
            return {**evidence, "status": "unavailable"}, raw, "Invalid symmetric magnitude."
        # The symmetric callout has a single valid magnitude. The lower output
        # from GetMinValue2 is invalid for this type and is only diagnostic.
        low = -high
    elif native_type not in BILATERAL_AND_LIMIT:
        return {**evidence, "status": "unsupported"}, raw, "This native type is unqualified."
    elif (low_status, high_status) != (0, 0) or low > high:
        return {**evidence, "status": "unavailable"}, raw, "The native offsets failed validation."
    return {**evidence, "status": "supported", "deviations": {
        "lower": length(low), "upper": length(high),
    }}, raw, ""


def observe_binding(session, assembly, components, binding, revision):
    logical_id = binding["logical_id"]
    target = binding["target"]
    record = dict(kind="cad_extraction", schema_version=1, logical_id=logical_id)
    raw = {"logical_id": logical_id, "target": target}
    source = None

    def failure(code, message, recovery):
        result = {**record, "status": "failed", "diagnostics": [
            diagnostic(logical_id, code, message, recovery),
        ]}
        if source is not None:
            result["source"] = source
        return result, raw

    if target["adapter"] != "solidworks" or len(target["occurrence_path"]) != 1:
        return failure("cad.binding_unavailable", "Expected one top-level SOLIDWORKS occurrence.",
                       "Bind a top-level occurrence explicitly.")
    matches = [component for component in components if [component.Name2] == target["occurrence_path"]]
    if not matches:
        return failure("cad.binding_missing", "The occurrence name did not match.",
                       "Check the active assembly configuration and exact occurrence name.")
    if len(matches) != 1:
        return failure("cad.binding_ambiguous", "Several occurrences matched.",
                       "Use a unique occurrence path.")

    try:
        component = matches[0]
        state = raw["GetSuppression2"] = component.GetSuppression2()
        config = raw["ReferencedConfiguration"] = component.ReferencedConfiguration
        if state not in RESOLVED:
            return failure("cad.binding_unavailable", f"Occurrence suppression state is {state}.",
                           "Resolve and unsuppress the occurrence in SOLIDWORKS.")
        if config != target["configuration"]:
            return failure("cad.binding_unavailable", f"Occurrence references {config!r}.",
                           "Check the declared referenced configuration.")
        part = session.wrap("IModelDoc2", component.GetModelDoc2())
        if part is None or part.GetType() != 1:
            return failure("cad.binding_unavailable", "The occurrence has no loaded part document.",
                           "Resolve the intended native part in SOLIDWORKS.")
        if config not in (part.GetConfigurationNames() or ()):
            return failure("cad.binding_unavailable", "The referenced part configuration was not found.",
                           "Check the installed part and the occurrence configuration.")
        dimension = session.wrap("IDimension", part.Parameter(target["dimension_id"]))
        if dimension is None:
            return failure("cad.binding_missing", "The named part dimension did not resolve.",
                           "Check the native parameter name including its sketch or feature.")
        source = {
            "adapter": "solidworks", "application": "SOLIDWORKS", "application_version": revision,
            "assembly": document_ref(assembly),
            "assembly_configuration": active_configuration(session, assembly).Name,
            "occurrence_path": [component.Name2], "document": document_ref(part),
            "configuration": config, "dimension_id": target["dimension_id"],
        }
        part_config = raw["part_active_configuration"] = active_configuration(session, part).Name
        raw["part_display_length_unit_code"] = part.GetUnits()[0]
        raw["FullName"] = dimension.FullName
        raw["GetType"] = dimension.GetType()
        if raw["GetType"] != 0:
            return failure("cad.read_failed", "The native dimension does not represent a length.",
                           "Bind an explicitly named linear or diameter dimension.")
        explicit = dimension.GetSystemValue3(3, config_names(config))
        if explicit is None or len(explicit) != 1:
            return failure("cad.read_failed", "Named-configuration read did not return one value.",
                           "Check the configuration and dimension availability.")
        raw["GetSystemValue3_specified"] = length(explicit[0])
        current = dimension.GetSystemValue3(1, None)
        if current and len(current) == 1:
            raw["GetSystemValue3_current"] = length(current[0])
    except (pythoncom.com_error, ValueError) as exc:
        return failure("cad.read_failed", f"Nominal read failed: {exc}",
                       "Check the exact part dimension and occurrence configuration.")

    try:
        tolerance, raw_bounds, reason = read_tolerance(session, dimension, part_config, config)
        raw["native_tolerance"] = raw_bounds
    except (pythoncom.com_error, ValueError, TypeError) as exc:
        tolerance, reason = {"status": "unavailable"}, f"Tolerance read failed: {exc}"
    warnings = []
    if reason:
        warnings.append(diagnostic(logical_id, "cad.tolerance_unresolved", reason,
                                   "Supply an explicit tolerance source in the case.", severity="warning"))
    return {**record, "status": "resolved", "source": source,
            "nominal": raw["GetSystemValue3_specified"], "tolerance": tolerance,
            "diagnostics": warnings}, raw


def observe(session, bindings):
    assembly = session.wrap("IModelDoc2", session.app.ActiveDoc)
    if assembly is None or assembly.GetType() != 2:
        raise RuntimeError("Open the intended resolved SOLIDWORKS assembly as the active document.")
    revision = session.app.RevisionNumber()
    components = top_components(session, assembly)
    observations = [observe_binding(session, assembly, components, binding, revision)
                    for binding in bindings]
    return {"application_revision": revision, "process_id": session.app.GetProcessID(),
            "records": [record for record, _ in observations],
            "raw": [raw for _, raw in observations]}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bindings", type=Path, help="JSON array of Chat 02 CAD binding objects")
    parser.add_argument("output", type=Path, help="New JSON file for records plus raw observations")
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL)
    args = parser.parse_args()
    bindings = json.loads(args.bindings.read_text(encoding="utf-8"))
    result = observe(Session(args.install), bindings)
    write_json(args.output, result)
    return int(any(record["status"] == "failed" for record in result["records"]))


if __name__ == "__main__":
    raise SystemExit(main())
