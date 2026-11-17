# StackOpt acceptance fixtures

This is the Chat 03 handoff. The fixture oracle and published expectations are independent of StackOpt. The cases describe a synthetic diametral clearance, not a qualified fit, manufacturing capability study, or SOLIDWORKS test.

| File | Use |
| --- | --- |
| [manual-case.json](manual-case.json) | v1 `CaseDocument` for the baseline and four permitted assignments, including the bore-only fix. |
| [cad-shaped-snapshot.json](cad-shaped-snapshot.json) | v1 `SnapshotDocument` with a CAD-bound case, two synthetic `CadExtractionRecord` values, the resolved problem and its warning. It has the same engineering inputs as the manual case. |
| [reference.json](reference.json) | Hand-derived drawing limits, both bounds at both operating endpoints, signed controlling terms in bore/shaft order, baseline and bore-only margins. |
| [report-cases.json](report-cases.json) | Twelve named allocation scenarios with authored clearance limits, optional fixture controls, and stable field expectations. |
| [diagnostic-cases.json](diagnostic-cases.json) | Four invalid authored inputs and one extraction with an unresolved selected tolerance, with expected exit statuses and error fields. |
| [shared-callout-case.json](shared-callout-case.json) | v1 manual case for physical aliases, independently varying occurrences of one callout, asymmetric and point intervals, and exact equality at both requirement limits. |
| [acceptance_oracle.py](../../tests/acceptance_oracle.py) and [test_acceptance_oracle.py](../../tests/test_acceptance_oracle.py) | Fixture materializer and five independent checks. They use only the Python standard library. |

## Hand calculation

At 20 °C, let the clearance be bore diameter minus shaft diameter. Nominals are 20.100 mm and 20.000 mm. Their constant expansion coefficients are 0.000023 K⁻¹ and 0.000012 K⁻¹. Assume common uniform part temperature, free linear expansion, independent manufactured dimensions and fixed reference drawing limits. There is no allowance for form, alignment, loads, deformation, temperature gradients, or statistical yield. Scores 0, 1 and 3 are synthetic penalties. The 0.050–0.150 mm requirement applies at all temperatures from −20 to 60 °C.

| Temperature | Bore factor | Shaft factor |
| ---: | ---: | ---: |
| −20 °C | 0.99908 | 0.99952 |
| 60 °C | 1.00092 | 1.00048 |

Both factors stay positive. For every choice in the benchmark, bore thermal growth per K exceeds shaft thermal growth per K, even for the smallest bore and largest shaft. Thus every corner is increasing with temperature. The lower bound uses the cold lower bore and cold upper shaft; the upper bound uses the hot upper bore and hot lower shaft. The factors multiply actual drawing limits, including the signed deviations.

| Design and controlling case | Bore term (mm) | Shaft term (mm) | Sum (mm) |
| --- | ---: | ---: | ---: |
| Baseline lower at −20 °C | +20.056531 | −20.015388 | **0.041143** |
| Baseline upper at 60 °C | +20.143515 | −19.984588 | **0.158927** |
| Bore-only lower at −20 °C | +20.0665218 | −20.015388 | **0.0511338** |
| Bore-only upper at 60 °C | +20.1335058 | −19.984588 | **0.1489178** |

For example, the baseline lower bound is `20.075 × 0.99908 − 20.025 × 0.99952` mm. Changing the bore callout from ±0.025 to ±0.015 mm changes its drawing limits from 20.075–20.125 to 20.085–20.115 mm. The shaft stays at 19.975–20.025 mm. The minimum margin is clearance minimum minus requirement minimum. The maximum margin is requirement maximum minus clearance maximum. The signs matter: the upper bore term decreases by 0.0100092 mm, so the upper margin increases by the same amount.

| Declared margin | Baseline (µm) | Bore-only (µm) | Recovery (µm) |
| --- | ---: | ---: | ---: |
| Minimum at −20 °C | −8.8570 | +1.1338 | +9.9908 |
| Maximum at 60 °C | −8.9270 | +1.0822 | **+10.0092** |

The shaft group varies fastest, so indices 0, 1, 2 and 3 are baseline/baseline, baseline/tight, tight/baseline and tight/tight. The three feasible assignments have scores 3, 1 and 4. Candidate 2 is the unique winner and still has only 1.0822 µm of limiting upper margin under this model.

The oracle reads the fixture dimensions as exact decimals and enumerates all combinations of drawing endpoints for each physical variable at each distinct operating endpoint. It substitutes the same length into every occurrence of a physical variable in the original chain. It does not use the production coefficient coalescing, sign-based bound selection, decimal parsing or allocation functions. Arithmetic in the corner loop traps inexact decimal operations.

## Failure and report evidence

- **One-sided and two-sided.** Always return both physical bounds and traces. Under the 0.055 mm minimum-only requirement the selected option is shaft-only, and its minimum margin is +0.0011358 mm. Under maximum-only the bore-only option wins, and no minimum margin or explanation is defined. With both original limits present, both fail at baseline; the signed stack and margin table above must be reproducible from the report.
- **Impossible.** For limits 0.070–0.130 mm, the tight/tight choice is still short by 0.0038734 mm at the minimum and exceeds the maximum by 0.0039106 mm. The worst violations for indices 0–3 are 0.028927, 0.0139198, 0.0189178 and 0.0039106 mm. Return index 3 as `closest_tested`, with both failed margins, no recommendation, and exit 6.
- **Closest by worst side, including a tie.** At fixed 20 °C, shaft baseline and a 0.080–0.120 mm requirement, the three bore choices yield envelopes 0.087–0.137, 0.065–0.135 and 0.065–0.115 mm. Worst violations are 0.017, 0.015 and 0.015 mm. Pick index 1 by stable order even though index 2 has a smaller sum of violations.
- **Interrupted.** Interrupt before the second assignment to get `closest_so_far` index 0 with 0.008927 mm worst violation, even though feasible assignments exist later. A two-evaluation budget sees feasible index 1 and returns it as `provisional_best`, with no closest diagnostic. Interrupt before evaluating any assignment to get `zero_tested`, with no closest candidate or explanation. All three return exit 7 and a `search.incomplete` warning. The independently computed baseline does not count as a tested assignment.
- **Ranking.** For tied scores, keep both best indices [1, 2] and use index 1 for the display comparison. With no objective, preserve feasible indices but omit the comparison. The missing-score case deletes a score from an option found only in *rejected* assignments; even then the declared search objective is unusable.
- **Governing temperature shift.** In the synthetic equal-CTE case, changing the bore moves the lower controlling temperature from 60 to −20 °C. At the common baseline temperature the lower margin improves by 0.0850782 mm. Moving to the new governing temperature subtracts 0.0001104 mm, giving 0.0849678 mm net. The upper bound remains governed by 60 °C.
- **Shared callout.** At baseline the chain reduces to `A₁ − A₂ − B + 0.5 C`, where `2A₁ − A₁` shares one drawn length but `A₂` varies separately. Baseline signed terms are `(+10, −10.2, −3.9, +0.525)` at the lower bound and `(+10.2, −10, −3.7, +0.525)` at the upper bound. These sum to −3.575 mm and −2.975 mm. The single option applies 10–10.1 mm to both A occurrences; the resulting bounds are −3.475 and −3.075 mm and tie both requirement limits exactly. Both bounds choose −20 °C on the temperature tie, and the minimum side is limiting on the margin tie.

Predicted input failures: an empty requirement has no decision criterion; 1 in exceeds 20 mm after exact normalization to 25.4 mm; a JSON number fails the decimal-text rule; a Boolean is not an integer version. All four fail before computing, with exit 3. The CAD negative case replaces the shaft tolerance evidence with `unsupported`. Since the case explicitly selects the CAD tolerance for the shaft, nominal success cannot rescue it. Expect `cad.tolerance_unresolved` for `shaft` at `/dimensions/1/tolerance`, exit 5 and no snapshot write. The successful CAD-shaped input reads both nominals in metres and uses only the shaft's CAD tolerance. Bore CAD ±0.024 mm deliberately disagrees with manual ±0.025 mm; retain both, use the latter, and expect `cad.tolerance_discrepancy`. The synthetic source labels do not establish native support.

## Running and consuming the fixtures

From the project root on Windows:

```powershell
py -3.12 -B -I -m unittest discover -s tests -p test_acceptance_oracle.py -v
py -3.12 -B -I tests/acceptance_oracle.py --export (Join-Path $env:TEMP 'stackopt-fixtures-new')
$env:PYTHONPATH = 'src'
py -3.12 -B -m unittest discover -s tests
```

Choose a **new** directory for export. It creates standalone cases including `bore-only-analysis.json`, `cad-bound-case.json`, and case variants named after their manifest IDs. `cad-extraction-records.json` and `selected-cad-tolerance-unresolved-records.json` are arrays for an injected adapter, not CLI inputs. Use `search_control` in the test harness: `interrupt_after` means stop between completed evaluations; the count budget is the v1 `SearchBudget` payload. Neither is an extra case field or a new CLI flag. Inject cancellation or set the count budget in the allocator or handler integration; do not use timing to reproduce these cases.

The reference and scenario manifests are fixture data, not new StackOpt schema kinds. The report manifest's `expected` is a projection of v1 output: compare `search` verbatim, `feasible_indices` to the ordered candidate indices, `ranking` fields to the corresponding keys, and compare `closest.candidate_index` with `closest.candidate.index`. Match baseline margins directly and comparison entries to `explanation` (role, index and per-side margins and attribution). For benchmark variants with no geometry override, compare both bounds and controlling trace contributions to `reference.json` even when only one margin is declared. Their same-temperature delta equals the margin delta and the governing-temperature delta is zero. Report changed callouts against the declared options and baseline deviations; for the interrupted baseline candidate the list is empty. Compare diagnostic code, severity, pointer and optional ID independently of human-readable message wording. An expected absent closest or comparison means the corresponding v1 field is omitted.

| Chat | What to consume |
| --- | --- |
| 04 · Resolution/replay | Resolve the manual case and the exported bound case with injected extraction records. Compare normalized values with the snapshot's `problem` and test source provenance separately. Use the exported negative cases and the diagnostic manifest. Replay the saved fixture offline. |
| 05 · Evaluation | Compare signed bounds, temperatures, and margins with the hand reference and check the standalone bore-only change. Use the shared-callout case for correlation and exact boundary equality. |
| 06 · Allocation | Consume the ordered candidate rows and the report manifest. Drive the explicit search prefixes and test the minimax tie, tied scores, and unranked cases. |
| 08 · Reporting | Use the report projections and the signed reference terms. Review whether someone can recover the failed requirement, permitted changes, and margins from terminal and JSON reports alone. Check the separate signed attribution for the temperature-shift case. |
| 09 · SOLIDWORKS | Run the live fixture on Windows with Chat 07's qualified installation and a designated two-part assembly. Record application version, occurrence paths, referenced configurations, named dimension IDs, raw values and units, source state and actual tolerance evidence for both extractions. Supply the bound case, original/rebuilt extraction arrays and exact controlled edit to Chat 10. Use manual tolerances where the native annotation is unqualified. |
| 10 · Integration | Materialize the cases, compare CLI reports to these projections, check exits 0/3/5/6/7 and output destination behavior, and capture the live snapshots from Chat 09. A suggested controlled edit is +0.001 mm bore nominal with offsets, shaft and model unchanged: this increases the lower and upper bounds by 0.00099908 and 0.00100092 mm, respectively. If the observed raw value differs, use the observed change and original units. Fresh replay should reflect that delta, and the original snapshot must still produce the original numbers. |

## Observed verification

The active project root is `ME Project`, without Git metadata. Chat 03 added only fixtures, their documentation and independent tests. Runtime source, architecture files, schemas and dependencies are unchanged. The default graph 0.1.1, architecture README, build plan and Chats 01–02 handoffs were checked; browser-local edits have no supplied export.

- `py -3.11/3.12/3.13 -B -m unittest discover -s tests` (separate commands with `PYTHONPATH=src`): **20 passed on each version**, including the five oracle checks. Isolated oracle discovery with `-I`: **5 passed**. Python removes the script directory for direct `-I` execution, so use the discovery command above for tests.
- Two exports into distinct new directories produced **24 byte-identical JSON files**. A probe of `python -m stackopt analyze MANUAL --json RESULT` returned exit 1 with the skeleton's unavailable-handler diagnostic and created no result file.
- A Python 3.12 probe passed the four invalid manual fixtures through the existing `validate_header` and `parse_requirement` helpers. Their exit status, code, severity and pointer all matched the manifest. The unsupported CAD case remains an expected extraction result for Chat 04.
- Fixture-side arithmetic and scenario expectations are verified. G01 still needs production resolution and replay, G02 needs comparison against the evaluator, G03 needs the allocator, and G06 needs actual reports. G04 needs the live fixture and G05 needs a clean installation that produces a result plus the real assembly review. No downstream acceptance gate was changed. The first real assembly still decides whether the Chat 11 joint-allocation gate applies.

The downstream implementation chats were not present in the project's chat list at handoff. Start Chat 04 with this README and the fixtures above. Chats 09 and 10 still need a designated live assembly and capture locations agreed between them.
