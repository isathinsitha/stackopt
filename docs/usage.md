# CLI and CAD guide

Run these commands from the repository root after `python -m pip install .`. The Python used for installation should also provide the `stackopt` entry point on `PATH`. You can use `python -m stackopt` in the same environment.

## Commands and output

| Command | Input | Output |
| --- | --- | --- |
| `stackopt analyze SOURCE` | Fully manual case or saved snapshot | Baseline bounds, signed controlling terms, margins, and requirement status |
| `stackopt allocate SOURCE` | Same input as `analyze` | Baseline plus search counts, feasible assignments, and ranking or a qualified closest failure where applicable |
| `stackopt extract solidworks --active --case CASE --out SNAPSHOT` | Bound case and active SOLIDWORKS assembly | Versioned snapshot with resolved inputs and extraction provenance |
| `stackopt extract freecad --records RECORDS --case CASE --out SNAPSHOT` | Bound case and JSON records exported from FreeCAD | Versioned snapshot with the same replay format |

Add `--json RESULT` to `analyze` or `allocate` to write a UTF-8 JSON report. Terminal reports go to stdout by default. Warnings and application diagnostics go to stderr. JSON mode also emits application errors as structured JSON on stderr. Snapshot and report writes replace destinations atomically after successful serialization.

| Exit | Meaning |
| --- | --- |
| `0` | Help, successful extraction, valid analysis, or complete search with a feasible assignment |
| `1` | Internal or output-write failure |
| `2` | Invalid command syntax |
| `3` | Invalid, unreadable, or incompatible input |
| `4` | CAD unavailable |
| `5` | Extraction failed |
| `6` | Complete search with zero feasible assignments |
| `7` | Incomplete search, including a cooperative `Ctrl+C` stop |

For `analyze`, check `baseline.meets_requirement` in the JSON even when the process exits `0`. Exit `6` applies only to the supplied discrete options and model. An interrupted `allocate` run reports how many assignments finished and qualifies any partial ranking.

## CAD extraction

The authored case supplies the chain, requirement, materials, temperatures, and permitted tolerance options. Each CAD binding identifies a specific native dimension. A case explicitly selects CAD or manual deviations for each dimension. If CAD deviations are required and the adapter cannot establish them, extraction fails. With manual deviations selected, the case supplies the source reference and offsets.

### SOLIDWORKS

Install `pywin32` in the CLI environment on Windows. Open and resolve the intended assembly in SOLIDWORKS, then make it the active document. Bind dimensions by occurrence path, referenced configuration, and the native `parameter@feature` name. See the [bound benchmark case](../examples/cad/solidworks/case.json) for the input shape.

```powershell
python -m pip install pywin32
stackopt extract solidworks --active --case my-assembly.json --out solidworks.snapshot.json
stackopt allocate solidworks.snapshot.json
```

The two-part fixture qualified nominal reads and bilateral, limit, and symmetric model tolerance reads on SOLIDWORKS 2026 SP2.1. The adapter reports tolerance evidence as unavailable when an occurrence's referenced configuration and the part's active configuration disagree. A supported nominal read can still be used with sourced manual tolerances. Drawing-only tolerance annotations require manual deviations.

To reproduce the live benchmark, start SOLIDWORKS with all documents closed. On a fresh clone, run the fixture generator from the repository root. Close the reopened fixture documents before running the verification driver with a fresh output directory. The generator accepts `--templates` and `--install` for non-default SOLIDWORKS paths.

```powershell
python spikes/solidworks_07/run_fixture.py evidence
$env:PYTHONPATH = (Resolve-Path 'spikes/solidworks_07').Path
python tests/live_solidworks.py (Join-Path $env:TEMP ('stackopt-sw-' + [guid]::NewGuid()))
```

### FreeCAD

Open, select, and recompute the intended `.FCStd` document. In FreeCAD's Python console, add the source directory from the checkout and export the explicitly bound properties. Use actual absolute paths in place of the examples below.

```python
from pathlib import Path
import sys

sys.path.insert(0, r"C:\path\to\stackopt\src")
from stackopt.adapters.freecad import export_active

export_active(Path(r"C:\path\to\freecad-case.json"), Path(r"C:\path\to\records.json"))
```

```powershell
stackopt extract freecad --case freecad-case.json --records records.json --out freecad.snapshot.json
stackopt allocate freecad.snapshot.json
```

The qualified path reads named `App::PropertyLength` properties on valid native `Part::Cylinder` objects in one recomputed document. Bind the internal object `Name` and the exact property name. Use `unconfigured` for the configuration and supply sourced manual tolerances. Qualification covers FreeCAD 1.1.4 on Windows x64. The operator selects the active document. Captured FreeCAD save state is `unknown`.

You can try the records-to-snapshot path without FreeCAD. The [example case and records](../examples/cad/freecad/) use the benchmark dimensions and replace captured machine paths with neutral provenance identifiers.

```bash
stackopt extract freecad --case examples/cad/freecad/case.json --records examples/cad/freecad/records.json --out freecad.snapshot.json
stackopt allocate freecad.snapshot.json
```

The [live FreeCAD driver](../tests/live_freecad.py) can generate a native fixture and fresh captures. It takes the path to the CLI's Python executable followed by a new output directory and runs under the Python supplied with FreeCAD.
