# StackOpt architecture workspace

The editor is adapted from the supplied Return Window architecture workspace. The default document specifies the proposed StackOpt system. Its acceptance gates start at **Not evaluated**.

Run from this directory:

```powershell
npm ci
npm run dev
```

Open the address printed by Vite. `npm run build` runs TypeScript checks and creates the production build. The editor saves changes in browser storage for its current origin. Export editable JSON to keep a portable copy. The first coding segment is **Build sequence → Runtime boundaries**.

## Design review for v0.1

| Boundary | Design decision |
|---|---|
| Process | A Python CLI owns dispatch and configuration. The numerical code has no dependency on CLI output, local paths, or CAD APIs. The SOLIDWORKS adapter talks to the desktop process during extraction. The FreeCAD exporter runs in FreeCAD's Python runtime and passes records through a local JSON file. |
| Invocation | `extract` accepts a bound case and either `solidworks --active` or `freecad --records RECORDS` to produce a snapshot. `analyze` and `allocate` accept a fully manual case or a saved snapshot. Mixed manual and CAD cases are resolved by `extract`. Replay validates the saved values directly. |
| Scope | One named signed linear functional quantity by default. Add joint evaluation if the first real assembly shares an adjustable callout across affected requirements. CAD models provide values for declared references. The engineer defines chain signs, limits, material properties and options. The model covers dimensional bounds under common uniform temperature and free expansion. |
| Identity | Use distinct logical IDs, physical variable IDs, and dimension/callout IDs. Repeating a physical variable combines its coefficients. Separate manufactured occurrences may vary independently. A shared callout option changes declared limits for all occurrences associated with that specific callout and applicable revision or configuration. Separate dimensions on the same drawing have separate choices. |
| CAD evidence | Identify the resolved document, occurrence, configuration, dimension and units. Record whether the extracted state was saved. Support explicit tolerance types and validate status before interpreting offsets. Drawing-only and unsupported model annotations can be provided in the case with an explicit source. |
| Error semantics | Reject invalid or incomplete inputs before computing. An analyzed clearance outside its limits is a valid analysis result. An exhaustive allocation search with zero feasible candidates proves infeasibility under the inputs. An incomplete search can return provisional findings and has its own status. |
| Precision | Persist physical numbers as decimal strings. For the linear reference model, use exact rational operations on parsed decimals and serialize the finite decimal result. Initial input units use exact decimal conversions (mm/m/in for length, °C/K for temperature, K⁻¹ for expansion coefficients). Store a CAD double through its round-trip decimal representation. Compare before rendering. Treat CAD precision as input uncertainty where it matters. |
| Scale | Begin with finite enumeration of declared options. Report the full and checked counts. Record any time or combination budget and distinguish a provisional result from a complete ranking. A future solver must reproduce small exhaustive cases. |
| ML | A data-dependent cost estimator can be considered only after obtaining representative supplier data. A validated estimate can enter the optional ranking objective. The geometric feasibility decision remains deterministic. |

## Contracts to freeze before coding the solver

| Record | Owning boundary | Draft fields |
|---|---|---|
| Case specification | Engineer → parser | Document kind and version; named functional chain; logical IDs; source bindings or manual nominal values; signed drawing deviations; at least one clearance limit; reference and operating temperatures; expansion coefficients; candidate intervals; optional objective basis. |
| Extraction record | CAD adapter → resolver | CAD application/version and document state; one outcome per binding; occurrence and configuration; source dimension ID; raw value and units; raw tolerance status/type; supported deviations if available; structured diagnostic and provenance. |
| Resolved snapshot | Resolver → evaluator or allocator | Versioned normalized values; physical/callout identities; chain coefficients; fully resolved baseline bounds; candidate options; model assumptions; requirement limits; source evidence. No external lookup is needed for replay. |
| Analysis result | Evaluator → renderer | Baseline envelope; min and max governing temperatures; signed margins for declared sides; controlling signed contributions; feasibility under the supplied model; traceable inputs and assumptions. |
| Allocation result | Allocator → renderer | Baseline; complete/incomplete status; checked and total counts; feasible choices or ranked results; tied and provisional outcomes; ranking provenance; candidate margins and controlling conditions; callout changes; margin recovery; closest-tested failure diagnostic. |
| Diagnostic | Application → CLI | Stable reason code, affected input/binding, severity and recovery hint. Document process exit behavior and stdout/stderr ownership alongside the schema. |

The graph records components, contracts, scientific assumptions and acceptance gates. The [CAD guide](../docs/usage.md#freecad) records FreeCAD's qualified nominal-only path. The first real assembly review and the SOLIDWORKS binding-authoring trial remain open. Additional CAD targets require separate qualification.

## Actionable results and release checks

- Require at least one clearance limit. Always report both physical clearance bounds. For each declared requirement side, identify its signed margin and controlling temperature.
- For the baseline and reported candidate, include signed dimensional contributions to each physical bound. Show changed callout limits and the change in each declared margin. Attribute contribution changes at a common temperature and side, and explicitly identify any shift in the governing temperature.
- When no evaluated option passes, report the closest tested candidate by minimum maximum violation across declared sides in mm, with stable candidate order for ties. Show its margins and temperatures as a diagnostic. A stopped search qualifies the candidate as closest evaluated so far. With zero evaluated candidates, leave the diagnostic candidate absent.
- Before freezing support for the first real assembly, check whether an adjustable callout affects multiple requirements. If it does, apply each candidate assignment across every affected chain and surface the limiting requirement and side. Otherwise identify the single-chain result scope. Try CAD binding discovery only if the live trial shows that locating identifiers is the bottleneck.
- The first actionable report check asks which requirement and side failed, which signed terms drove the bound, and what permitted change recovers how much margin. Include min-only, max-only, two-sided, genuinely infeasible and interrupted cases. The bore-only example must show the upper margin moving from −8.9270 µm to +1.0822 µm, a gain of 10.0092 µm.
