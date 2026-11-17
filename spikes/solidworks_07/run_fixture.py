"""Create and exercise a fresh disposable two-part fixture owned by Chat 07."""

from __future__ import annotations

import argparse
from pathlib import Path

from probe import (
    DEFAULT_INSTALL, Session, active_configuration, config_names, length, observe,
    top_components, write_json,
)


HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATES = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates")


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def require_status(actual, expected, step):
    if actual != expected:
        raise RuntimeError(f"{step} returned {actual!r}, expected {expected!r}.")


def select(session, model, name, kind):
    extension = session.wrap("IModelDocExtension", model.Extension)
    require(extension.SelectByID2(name, kind, 0, 0, 0, False, 0, None, 0),
            f"Could not select {name!r} ({kind}).")


def save(model, path):
    ok, errors, warnings = model.SaveAs4(str(path), 0, 1, 0, 0)
    require(ok and not errors, f"Save failed for {path.name}: {errors=}, {warnings=}.")
    print(f"Saved {path.name}: {errors=}, {warnings=}", flush=True)


def rebuild(model):
    require(model.ForceRebuild3(False), f"Rebuild failed for {model.GetTitle()}.")


def show_configuration(session, model, config):
    if active_configuration(session, model).Name != config:
        require(model.ShowConfiguration2(config), f"Could not activate {config!r}.")
    require_status(active_configuration(session, model).Name, config, "Active configuration")


def create_part(session, templates, path, name, radius, kind, *, tube=False):
    model = session.wrap("IModelDoc2", session.app.NewDocument(str(templates / "Part.PRTDOT"), 0, 0, 0))
    require(model, "SOLIDWORKS did not create the part from Part.PRTDOT.")
    select(session, model, "Front Plane", "PLANE")
    sketch = session.wrap("ISketchManager", model.SketchManager)
    sketch.InsertSketch(True)
    if tube:
        require(sketch.CreateCircleByRadius(0, 0, 0, 0.016), "Outer profile failed.")
    circle = session.wrap("ISketchSegment", sketch.CreateCircleByRadius(0, 0, 0, radius))
    require(circle, "Named circular profile failed.")
    model.ClearSelection2(True)
    require(circle.Select4(False, None), "Could not select the named circle.")
    # AddDiameterDimension2 opens a synchronous Modify dialog when this preference is on.
    input_dimension_on_create = 10
    old_preference = session.app.GetUserPreferenceToggle(input_dimension_on_create)
    try:
        session.app.SetUserPreferenceToggle(input_dimension_on_create, False)
        display = session.wrap("IDisplayDimension", model.AddDiameterDimension2(radius * 1.6, radius, 0))
    finally:
        session.app.SetUserPreferenceToggle(input_dimension_on_create, old_preference)
    require(display, "Could not add a driving diameter to the circle.")
    dimension = session.wrap("IDimension", display.GetDimension2(0))
    dimension.Name = name
    dim_id = "@".join(dimension.FullName.split("@")[:2])
    sketch_name = dim_id.split("@")[1]
    sketch.InsertSketch(True)
    model.ClearSelection2(True)
    select(session, model, sketch_name, "SKETCH")
    features = session.wrap("IFeatureManager", model.FeatureManager)
    require(features.FeatureExtrusion3(
        True, False, False, 0, 0, 0.008, 0, False, False, False, False,
        0, 0, False, False, False, False, True, False, True, 0, 0, False,
    ), "Could not extrude the fixture profile.")
    dimension = session.wrap("IDimension", model.Parameter(dim_id))
    base = active_configuration(session, model).Name
    require(set_tolerance(session, dimension, kind, -0.000025, 0.000025),
            "Could not set baseline model tolerance.")
    if tube:
        configs = session.wrap("IConfigurationManager", model.ConfigurationManager)
        require(configs.AddConfiguration2("Alternate", "CAD spike contrast", "", 0, "", "", False),
                "Alternate configuration creation failed.")
        show_configuration(session, model, "Alternate")
        dimension = session.wrap("IDimension", model.Parameter(dim_id))
        require_status(dimension.SetSystemValue3(0.0209, 3, config_names("Alternate")), 0,
                       "Set Alternate bore diameter")
        require(set_tolerance(session, dimension, kind, -0.00004, 0.00004),
                "Could not set Alternate model tolerance.")
        rebuild(model)
        show_configuration(session, model, base)
    rebuild(model)
    save(model, path)
    return model, dim_id, base


def set_tolerance(session, dimension, kind, lower, upper):
    tolerance = session.wrap("IDimensionTolerance", dimension.Tolerance)
    tolerance.Type = kind
    require_status(tolerance.Type, kind, "Set model tolerance type")
    if lower is None or upper is None:
        return None
    # The fixture uses the active configuration. SetValues2 did not update the
    # getter values in the initial marshalling trials on this installation.
    return tolerance.SetValues(lower, upper)


def activate(session, model):
    result, error = session.app.ActivateDoc3(model.GetTitle(), False, 1, 0)
    require(result is not None and error in {0, 2}, f"Could not activate {model.GetTitle()}: {error}.")


def binding(logical_id, occurrence, config, dim_id):
    return {"logical_id": logical_id, "target": {
        "adapter": "solidworks", "occurrence_path": [occurrence],
        "configuration": config, "dimension_id": dim_id,
    }}


def occurrence(session, assembly, target):
    name = target["occurrence_path"][0]
    return next(item for item in top_components(session, assembly) if item.Name2 == name)


def fixture(session, output, templates):
    # This fresh directory is the only designated target for all writes and CAD edits.
    output.mkdir()
    native = output / "fixture"
    native.mkdir()
    bore_path = native / "Chat07-Bore.SLDPRT"
    shaft_path = native / "Chat07-Shaft.SLDPRT"
    assembly_path = native / "Chat07-Reference.SLDASM"
    print("Live revision:", session.app.RevisionNumber(), flush=True)
    bore, bore_dim, bore_config = create_part(session, templates, bore_path, "BoreDiameter", 0.01005, 2, tube=True)
    _, shaft_dim, shaft_config = create_part(session, templates, shaft_path, "ShaftDiameter", 0.010, 2)
    model = session.wrap("IModelDoc2", session.app.NewDocument(str(templates / "Assembly.ASMDOT"), 0, 0, 0))
    require(model, "SOLIDWORKS did not create the assembly from Assembly.ASMDOT.")
    assembly = session.wrap("IAssemblyDoc", model)
    occurrences = []
    for path, config in ((bore_path, bore_config), (shaft_path, shaft_config)):
        component = session.wrap("IComponent2", assembly.AddComponent5(str(path), 0, "", True, config, 0, 0, 0))
        require(component, f"Could not insert {path.name} as a resolved occurrence.")
        occurrences.append(component.Name2)
    rebuild(model)
    bindings = [binding("bore", occurrences[0], bore_config, bore_dim),
                binding("shaft", occurrences[1], shaft_config, shaft_dim)]
    write_json(output / "bindings.json", bindings)
    write_json(output / "unsaved-assembly.json", observe(session, bindings))
    save(model, assembly_path)
    write_json(output / "before.json", observe(session, bindings))

    activate(session, bore)
    dim = session.wrap("IDimension", bore.Parameter(bore_dim))
    require_status(dim.SetSystemValue3(0.02012, 3, config_names(bore_config)), 0,
                   "Controlled bore change 20.100 to 20.120 mm")
    rebuild(bore)
    activate(session, model)
    rebuild(model)
    write_json(output / "after.json", observe(session, bindings))

    switch_and_probe(session, output, model, bindings, bore)
    probe_tolerances(session, output, model, bindings, bore)
    require_status(occurrence(session, model, bindings[1]["target"]).SetSuppression2(0), 2,
                   "Suppress the fixture shaft")
    write_json(output / "suppressed-shaft.json", observe(session, bindings))
    print("Fixture saved at baseline. Trial edits were kept in memory.", flush=True)

    close_fixture(session, native)
    opened, errors, warnings = session.app.OpenDoc6(str(assembly_path), 2, 65, "", 0, 0)
    require(opened is not None and not errors, f"Baseline reopen failed: {errors=}, {warnings=}.")
    print(f"Reopened baseline: {errors=}, {warnings=}", flush=True)
    write_json(output / "reopened.json", observe(session, bindings))


def switch_and_probe(session, output, assembly, bindings, bore):
    def get_occurrence():
        return occurrence(session, assembly, bindings[0]["target"])

    get_occurrence().ReferencedConfiguration = "Alternate"
    rebuild(assembly)
    alternative = [binding("bore", get_occurrence().Name2, "Alternate",
                           bindings[0]["target"]["dimension_id"]), bindings[1]]
    write_json(output / "configuration-switched.json", observe(session, alternative))
    missing = binding("missing_dimension", get_occurrence().Name2, "Alternate", "Missing@Sketch1")
    write_json(output / "wrong-targets.json", observe(session, [bindings[0], missing]))
    activate(session, bore)
    show_configuration(session, bore, "Alternate")
    activate(session, assembly)
    write_json(output / "configuration-aligned.json", observe(session, alternative))
    get_occurrence().ReferencedConfiguration = bindings[0]["target"]["configuration"]
    rebuild(assembly)


def probe_tolerances(session, output, assembly, bindings, bore):
    config = bindings[0]["target"]["configuration"]
    dim_id = bindings[0]["target"]["dimension_id"]
    rows = []
    for name, kind, lower, upper in (
        ("none", 0, None, None), ("basic", 1, None, None),
        ("bilateral_asymmetric", 2, -0.000013, 0.000031),
        ("bilateral_positive_only", 2, 0, 0.000031),
        ("limit", 3, -0.000014, 0.000032),
        ("symmetric", 4, -0.000016, 0.000016),
        ("minimum", 5, -0.000018, 0.000034),
        ("maximum", 6, -0.000019, 0.000035),
    ):
        activate(session, bore)
        show_configuration(session, bore, config)
        dim = session.wrap("IDimension", bore.Parameter(dim_id))
        set_result = set_tolerance(session, dim, kind, lower, upper)
        rebuild(bore)
        activate(session, assembly)
        rebuild(assembly)
        run = observe(session, bindings[:1])
        rows.append({"trial": name, "requested_type": kind,
                     "requested_deviations": {"lower": length(lower), "upper": length(upper)}
                     if lower is not None else None,
                     "SetValues": set_result, **run})
    write_json(output / "tolerance-matrix.json", rows)


def close_fixture(session, native):
    """Discard only the three disposable documents under this exact directory."""
    for name in ("Chat07-Reference.SLDASM", "Chat07-Bore.SLDPRT", "Chat07-Shaft.SLDPRT"):
        expected = native / name
        model = session.wrap("IModelDoc2", session.app.GetOpenDocumentByName(str(expected)))
        if model is not None:
            require_status(Path(model.GetPathName()).resolve(), expected.resolve(), "Fixture path")
            session.app.CloseDoc(model.GetTitle())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="New directory name inside spikes/solidworks_07")
    parser.add_argument("--templates", type=Path, default=DEFAULT_TEMPLATES)
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL)
    args = parser.parse_args()
    output = (HERE / args.directory).resolve()
    if output.parent != HERE or output.exists():
        parser.error("Select a fresh direct child of the Chat 07 directory.")
    for name in ("Part.PRTDOT", "Assembly.ASMDOT"):
        if not (args.templates / name).is_file():
            parser.error(f"Missing fixture template: {args.templates / name}")
    session = Session(args.install)
    if session.app.GetDocumentCount() != 0:
        parser.error("Use an empty SOLIDWORKS session for fixture construction.")
    fixture(session, output, args.templates)


if __name__ == "__main__":
    main()
