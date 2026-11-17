"""Capture dimensions from downloaded LIGO parts in a new inspection assembly.

Requires Windows, a running SOLIDWORKS session with documents closed, pywin32,
and an installed StackOpt. The assembly only supplies occurrence identities
for extraction. Its parts are separated and have no assembly mates.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "spikes/solidworks_07"))
from probe import DEFAULT_INSTALL, Session, active_configuration
from run_fixture import DEFAULT_TEMPLATES, rebuild, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path, help="Directory created by download_sources.py")
    parser.add_argument("output", type=Path, help="New directory for the inspection assembly and capture")
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--templates", type=Path, default=DEFAULT_TEMPLATES)
    args = parser.parse_args()
    output = args.output.resolve()
    sources = {
        "Sleeve": args.sources / "D1000860, Stage 0-1 Locker, aLIGO BSC-ISI.SLDPRT",
        "Pin": args.sources / "D047935_Locker_Spherical_Pin.SLDPRT",
    }
    manifest = json.loads(Path(__file__).with_name("sources.json").read_text(encoding="utf-8"))
    hashes = {source["filename"]: source["sha256"] for source in manifest["files"]}
    for source in sources.values():
        assert sha256(source.read_bytes()).hexdigest() == hashes[source.name], source.name
    session = Session(args.install)
    assert session.app.GetDocumentCount() == 0, "Use a SOLIDWORKS session with documents closed."
    output.mkdir(parents=True)
    opened = []
    try:
        for name, source in sources.items():
            path = output / f"{name}.SLDPRT"
            copyfile(source, path)
            document, errors, warnings = session.app.OpenDoc6(str(path), 1, 3, "", 0, 0)
            assert document is not None and errors == 0, (name, errors, warnings)
            part = session.wrap("IModelDoc2", document)
            opened.append(part.GetTitle())
            assert active_configuration(session, part).Name == "Default"
        model = session.wrap("IModelDoc2", session.app.NewDocument(
            str(args.templates / "Assembly.ASMDOT"), 0, 0, 0,
        ))
        assert model is not None
        opened.append(model.GetTitle())
        assembly = session.wrap("IAssemblyDoc", model)
        occurrences = []
        for index, name in enumerate(sources):
            component = session.wrap("IComponent2", assembly.AddComponent5(
                str(output / f"{name}.SLDPRT"), 0, "", True, "Default", index * 0.15, 0, 0,
            ))
            assert component is not None
            occurrences.append(component.Name2)
        rebuild(model)
        save(model, output / "Inspection.SLDASM")
        opened[-1] = model.GetTitle()
        case = json.loads(Path(__file__).with_name("case.json").read_text(encoding="utf-8"))
        for dimension, occurrence, parameter in zip(
            case["dimensions"], occurrences, ("D1@Sketch1", "D2@Sketch1"), strict=True,
        ):
            dimension["nominal"] = {"kind": "cad", "target": {
                "adapter": "solidworks", "occurrence_path": [occurrence],
                "configuration": "Default", "dimension_id": parameter,
            }}
        bound = output / "bound-case.json"
        bound.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        subprocess.run([
            sys.executable, "-m", "stackopt", "extract", "solidworks", "--active",
            "--case", str(bound), "--out", str(output / "live.snapshot.json"),
        ], check=True)
    finally:
        for title in reversed(opened):
            session.app.CloseDoc(title)
    for name, source in sources.items():
        assert sha256(source.read_bytes()).hexdigest() == hashes[source.name]
        assert sha256((output / f"{name}.SLDPRT").read_bytes()).hexdigest() == hashes[source.name]


if __name__ == "__main__":
    main()
