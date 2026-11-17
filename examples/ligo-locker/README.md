# LIGO Stage 0-1 locker drawing study

This case uses public drawings and native parts for the Advanced LIGO BSC-ISI Stage 0-1 locker. The decision studied is whether to keep the issued sleeve bore limits or restore the wider interval from an earlier drawing. The comparison criterion is to preserve the size-clearance envelope derived from the revised drawing. StackOpt's author selected that criterion for this study. The source documents supply the dimensions and revisions, while owner confirmation of the assembly's functional limits remains pending.

## Source inputs

The assembly is D1000854-v3, Stage 0-1, sheet 1. Its bill of materials identifies the sleeve and pin below. Each part drawing also has one sheet. The change record identifies an increase in the small sleeve bore from 1.5000 to 1.5005 inches. [Assembly drawing record](https://dcc.ligo.org/LIGO-D1000854/public), [change record E1000353](https://dcc.ligo.org/LIGO-E1000353/public)

| Input | Drawing limits in inches | Source |
| --- | --- | --- |
| Issued sleeve small bore | 1.5005–1.5010 | D1000860-v2, section B-B, Ø1.5005 +.0005/−.0000 |
| Earlier sleeve small bore | 1.5000–1.5020 | D1000860-v1, section B-B, Ø1.500 +.002/−.000 |
| Pin spherical diameter | 1.4995–1.5000 | D047935-v4, Ø1.5000 +.0000/−.0005 |
| Study clearance limits | 0.0005–0.0015 | Derived from the issued bore and pin drawing endpoints |

The earlier sleeve interval is compared with the same v4 pin to isolate the sleeve change. Both sleeve drawings apply their dimensions after coating. The source materials for sleeve and pin are AISI 440C per AMS 5630. [Sleeve v2](https://dcc.ligo.org/LIGO-D1000860-v2/public), [sleeve v1](https://dcc.ligo.org/LIGO-D1000860-v1/public), [pin v4](https://dcc.ligo.org/LIGO-D047935-v4/public)

The native pin uses a radius parameter, so the signed chain is `clearance = +sleeve_bore − 2 × pin_sphere_radius`. Its nominal radius is 0.7500 in, with deviations −0.00025/+0 in. This is half the drawing's diameter and deviations. The proposed restoration of v1 limits is expressed at the unchanged v2 bore nominal with deviations −0.0005/+0.0015 in. Revisions and the Stage 0-1 application are explicit in the callout identities. The extracted native configuration is `Default`.

## Model and decision

The analysis compares size limits at an assumed common reference state of 20 °C. Reference and operating temperatures are equal. The zero expansion coefficients disable thermal effects for this comparison. Material expansion data and operating temperatures still need sourcing for a thermal decision.

| Sleeve limits | Clearance (µm) | Margin at minimum (µm) | Margin at maximum (µm) | Preserves study envelope |
| --- | ---: | ---: | ---: | --- |
| Keep v2 | 12.7–38.1 | 0 | 0 | Yes |
| Restore v1 interval | 0–63.5 | −12.7 | −25.4 | No |

The standalone decimal calculation enumerates the drawing endpoints using the full spherical diameter. It agrees exactly with both manual input and CAD snapshot replay. StackOpt tests two assignments and finds only the issued interval feasible against the declared study criterion. It reports an unranked feasible set because this case supplies no cost objective. [Independent calculation](independent_check.py), [captured check result](independent-check.json)

Keep the issued sleeve limits for this comparison. Restoring the earlier interval loses the 12.7 µm guaranteed diametral size separation and increases the upper clearance by 25.4 µm. The earlier interval's controlling study violation is its upper bore limit combined with the pin's lower diameter limit. The issued case touches both study limits, with zero reserve relative to that chosen envelope. Its positive physical size separation is 12.7 µm.

## Live extraction and offline reproduction

The published native parts were opened on SOLIDWORKS 2026 SP2.1, API `34.2.1`. Copies named `Sleeve` and `Pin` were placed apart in a newly created inspection assembly to provide top-level occurrence bindings. The assembly has no mates. The capture reads `Sleeve-1`, `Default`, `D1@Sketch1` as 0.0381127 m and `Pin-1`, `Default`, `D2@Sketch1` as 0.01905 m. Those match the drawing bore nominal and half the pin diameter. A separate read confirmed that the pin parameter's display type is radial (`5`) with `Diametric` false.

Both CAD parameters lack native model tolerances. The case explicitly supplies drawing deviations. Both parts reported a modified in-memory state. The capture driver made no parameter writes or part saves, and the downloaded originals and inspection copies retained their source hashes. The snapshot preserves the missing-tolerance and modified-state warnings.

The public snapshot replaces machine-specific document IDs, paths and matching diagnostic references with neutral labels. Numerical inputs, bindings, API revision, observed states and warnings remain in the snapshot. It is a publication copy of the live capture. Originals stay in the local evidence directory. [Snapshot](cad.snapshot.json), [download URLs and SHA-256 hashes](sources.json)

Run from the repository root after installing StackOpt in the same Python environment.

```bash
python -m pip install --no-deps .
stackopt analyze examples/ligo-locker/case.json
stackopt allocate examples/ligo-locker/case.json
stackopt analyze examples/ligo-locker/cad.snapshot.json
stackopt allocate examples/ligo-locker/cad.snapshot.json
python examples/ligo-locker/independent_check.py
```

The independent script imports only the standard library and invokes the installed CLI through subprocesses. It checks both sleeve intervals through `analyze`, then checks manual and snapshot `analyze` and `allocate`. It verifies both bounds, temperatures, margins, signed contribution sums and search results.

To download the original public drawings, three native parts and the assembly procedure into a new directory, run the command below. The downloader checks each binary file's recorded hash before writing it. Keep downloaded assets and raw machine-specific captures outside the tracked public files.

```bash
python examples/ligo-locker/download_sources.py tests/ligo_download_evidence
```

For fresh CAD extraction on the qualified Windows desktop, install `pywin32` in a separate CAD environment and start SOLIDWORKS with documents closed. The capture script uses the repository's existing fixture helpers and accepts `--install` and `--templates` for other installation paths. Choose a new output directory.

```powershell
python -m pip install pywin32
python examples/ligo-locker/capture_solidworks.py tests/ligo_download_evidence tests/ligo_capture_evidence
stackopt analyze tests/ligo_capture_evidence/live.snapshot.json
stackopt allocate tests/ligo_capture_evidence/live.snapshot.json
python examples/ligo-locker/independent_check.py --snapshot tests/ligo_capture_evidence/live.snapshot.json
```

## Engineering review still required

The scalar model answers the stated size-envelope comparison. To decide assembled local clearance, include the effect of the pin's concentricity control, sleeve runout, installation alignment, housing and post constraints, loads and any part-temperature differences. Halving diametral clearance gives radial size separation for concentric ideal geometry. The actual minimum local gap depends on those additional effects.

The adjustable bore also participates in the spherical limiting interface. Identify the approved insertion criterion, required locked restraint or allowable play, and clearance during stage movement before approving a change. Their numerical requirements and applicability to one shared drawing option remain unresolved. The v1 CLI evaluates one chain and one requirement per case. This study retains that scope.

The Stage 0-1 paragraph of E1000615-v3 names sleeve D1000875, while the D1000854-v3 assembly bill of materials specifies D1000860. This study uses the assembly bill of materials and matching Stage 0-1 part drawing. A case owner should resolve that procedure inconsistency during review. [Assembly procedure record](https://dcc.ligo.org/LIGO-E1000615/public)

G05 and the engineering release review remain open. This public drawing study establishes reproducible source transcription, nominal extraction and interval arithmetic. Owner review must establish whether the chosen criterion answers the actual assembly decision.

A review request for the user to send follows.

> StackOpt reproduces a public LIGO locker drawing comparison. The issued sleeve and pin limits give 12.7–38.1 µm diametral size clearance. Restoring the earlier sleeve interval gives 0–63.5 µm. I used preservation of the issued envelope as the study criterion. Could you review whether that criterion answers the drawing decision, and identify the alignment, locked-play or motion requirements that also apply?
