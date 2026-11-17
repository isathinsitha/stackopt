# First real-assembly validation

**Open.** The development build has fixture verification. The project still needs a representative assembly with a named drawing decision. [Case intake form](case-intake.md)

## Verified evidence

The clean Windows Python 3.12 install passed `pip check` and all 84 tests at `81e80ca`. All six Linux and Windows CI jobs passed on that commit. The saved native SOLIDWORKS and FreeCAD fixture snapshots reproduced eight analysis and allocation reports byte for byte, with matching exit codes. Reimporting both saved FreeCAD record sets also reproduced their snapshots. The live extraction evidence is limited to the fixture and CAD versions described in the [CAD guide](usage.md#cad-extraction). [CI run](https://github.com/isathinsitha/stackopt/actions/runs/44128744463)

### Independent benchmark check

The synthetic fixture defines clearance as bore diameter minus shaft diameter, with an allowable range of 0.050–0.150 mm. The independent check enumerated the eight combinations of drawing endpoints and common temperature endpoints for each assignment. It scaled each actual drawing limit by `1 + α(T − 20 °C)` using the fixture's material coefficients. The extrema occur at the temperature endpoints because the clearance for each dimensional corner is affine in temperature. All four assignments matched the installed CLI exactly. [Fixture inputs and hand calculation](../examples/acceptance-v1/README.md#hand-calculation)

| Bore tolerance (mm) | Shaft tolerance (mm) | Clearance (mm) | Margin at minimum (µm) | Margin at maximum (µm) |
| ---: | ---: | ---: | ---: | ---: |
| ±0.025 | ±0.025 | 0.041143–0.158927 | −8.8570 | −8.9270 |
| ±0.025 | ±0.010 | 0.0561358–0.1439198 | +6.1358 | +6.0802 |
| ±0.015 | ±0.025 | 0.0511338–0.1489178 | +1.1338 | +1.0822 |
| ±0.015 | ±0.010 | 0.0661266–0.1339106 | +16.1266 | +16.0894 |

StackOpt evaluated all four assignments and found three feasible. With the fixture's illustrative penalties, it ranked the bore-only change first. Its limiting margin is +1.0822 µm at 60 °C, with the bore at its upper drawing limit and the shaft at its lower limit. This is a decision for the synthetic benchmark.

From the repository root, these commands reproduce the public benchmark and exercise the separate standard-library corner oracle. The saved CAD-shaped snapshot uses synthetic records. The FreeCAD records example captures the same fixture geometry with public provenance labels.

```bash
python -m pip install --no-deps .
python -B -m unittest discover -s tests -p test_acceptance_oracle.py -v
stackopt analyze examples/acceptance-v1/manual-case.json
stackopt allocate examples/acceptance-v1/manual-case.json
stackopt allocate examples/acceptance-v1/cad-shaped-snapshot.json
stackopt extract freecad --records examples/cad/freecad/records.json --case examples/cad/freecad/case.json --out freecad-fixture.snapshot.json
stackopt allocate freecad-fixture.snapshot.json
```

## Evidence needed for the engineering review

1. Record the source drawing revision and configuration, the proposed decision, all affected requirements, the signed chains, and the permitted drawing limits. Confirm the source and applicability of any material and operating inputs.
2. Check that each functional quantity can be represented by a signed linear chain. For a local running gap, check the effect of alignment, geometry, deformation and differences in part temperatures on the decision. If one adjustable callout affects more than one requirement, evaluate the same candidate assignment against every affected requirement before recommending a change. The v1 CLI evaluates one chain per case.
3. Compare baseline and candidate bounds and margins against arithmetic derived independently from the source. Where CAD extraction is supported and available, confirm the bound values and configuration, save a snapshot, and replay analysis and allocation offline. Resolve discrepancies before recording the controlling callout, limiting requirement and side, and supported decision. Record the case owner's review where engineering judgment is needed.

The engineering part of the packaging and release gate (G05) stays open pending this evidence. A public case record should use values cleared for sharing. Hold original drawings and CAD, supplier data, and snapshots containing machine-specific paths privately. [Release checks](../ARCHITECTURE.md#actionable-results-and-release-checks)
