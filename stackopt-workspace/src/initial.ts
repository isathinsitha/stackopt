import { architectureSchema, defaultView, emptyAlgorithm, newComponent, newVariable } from './schema'
import type { Component, Connection, Gate, Group } from './schema'

const groups: Group[] = [
  { id:'cad',name:'CAD integration',summary:'Occurrence · configuration · annotations',phase:'offline',tone:'data',description:'Optional read-only extraction from a running CAD session. The first adapter targets a resolved SOLIDWORKS assembly. Manual cases and snapshotted analysis require no CAD.' },
  { id:'runtime',name:'Local application',summary:'Python package · CLI · orchestration',phase:'runtime',tone:'neutral',description:'One local process dispatches extract, analyze and allocate. The SOLIDWORKS process is external and used only during extraction. No service, database or CAD writeback is part of v0.1.' },
  { id:'contracts',name:'Input contracts',summary:'Case file · dimensions · requirements',phase:'runtime',tone:'data',description:'The case supplies design intent, explicit baseline tolerance sources, allowed options, and operating assumptions. CAD supplies the selected nominal values and qualified annotations.' },
  { id:'resolve',name:'Resolution & replay',summary:'Validation · provenance · snapshot',phase:'runtime',tone:'data',description:'Build one immutable-in-use, versioned representation of the complete resolved problem. The case file, CAD extraction record and replay snapshot serve distinct purposes.' },
  { id:'analysis',name:'Dimensional analysis',summary:'Signed intervals · thermal endpoints',phase:'runtime',tone:'constraint',description:'Evaluate one signed one-dimensional functional chain across the declared common part temperature range. The model assumes free expansion, constant coefficients and independently bounded physical dimensions.' },
  { id:'allocation',name:'Tolerance allocation',summary:'Discrete alternatives · hard constraints',phase:'runtime',tone:'decision',description:'Select among user-declared drawing options. Evaluate hard engineering limits for every tested candidate. Use comparable declared scores for ranking and distinguish exhausted search from incomplete search.' },
  { id:'pack',name:'Results & diagnostics',summary:'Terminal · JSON · failure outcomes',phase:'runtime',tone:'neutral',description:'Return structured evidence first, then render to terminal or JSON. Preserve source values, constraints, margin and the distinction between input errors, infeasibility and execution errors.' },
  { id:'verify',name:'Verification & release',summary:'Numerical tests · CAD fixtures · CLI',phase:'assurance',tone:'constraint',description:'Verify core mathematics independently, adapter behavior against a real CAD installation, and replay on a machine without CAD. Gate public connector support on recorded evidence.' },
  { id:'research',name:'Optional ML research',summary:'Cost estimates · held-out validation',phase:'assurance',tone:'neutral',description:'Future experiment gated by representative quote or process data. A qualified estimate would supply ranking inputs. Dimensional feasibility remains an explicit calculation.' },
  { id:'build',name:'Build sequence',summary:'Ordered implementation segments',phase:'assurance',tone:'decision',description:'Implement the runtime boundary and contracts first. Define expected outputs before the model is implemented. Spike SOLIDWORKS early to reduce integration uncertainty.' },
]

const components: Component[] = []
function add(group: string, id: string, name: string, category: Component['category'], module: string, description: string, detail: Partial<Component> = {}) {
  components.push({
    ...newComponent(id,group,category,name), purpose: description.split('. ')[0].replace(/\.$/,'')+'.', description,
    module, technology:[module], status:'planned', ...detail,
  })
}
function model(group: string, id: string, name: string, module: string, description: string, details: Partial<NonNullable<Component['algorithm']>>) {
  add(group,id,name,'Algorithm',module,description,{algorithm:{...emptyAlgorithm,name,description,...details}})
}
function gate(group: string, id: string, name: string, code: string, acceptance: string, failure: string, output: string) {
  const record: Gate = { code, stage:group, acceptance, failure, result:'Not evaluated', output }
  add(group,id,name,'Validation','tests/',acceptance,{gate:record,classification:'Architecture'})
}

add('cad','solidworks','SOLIDWORKS session','Infrastructure','Windows COM','Running desktop session with an explicitly selected, resolved assembly. Capture path and assembly configuration, and identify an unsaved or modified source state.')
add('cad','bindings','Occurrence binding','Data processor','adapters/solidworks.py','Resolve the configured occurrence path, referenced part configuration and named dimension. A duplicate or suppressed target stops extraction. Top-level assemblies are the first supported case.',{risks:'Reading the part document’s active configuration can return a plausible value for the wrong occurrence.'})
add('cad','annotations','Native dimension read','Data processor','adapters/solidworks.py','Read the configured nominal length. Read tolerance type and status before interpreting optional offsets. Preserve raw units and reference the exact source. Leave unsupported tolerances unresolved.')
add('cad','extraction','Extraction record','Storage artifact','adapters/contract.py','Return nominal length, optional supported deviations, source units, occurrence, configuration, CAD identifiers, and structured extraction diagnostics.')
add('cad','secondary-cad','FreeCAD exporter','Data processor','adapters/freecad.py','The FreeCAD Python runtime reads explicit native cylinder length properties from one recomputed FCStd document. Export v1 records in mm and use sourced manual tolerances. The benchmark passed on Windows x64 with FreeCAD 1.1.4. Qualify additional CAD targets only with a concrete use case and representative files.',{priority:'P2',status:'validated'})

add('runtime','cli','CLI entry point','API','cli.py','Parse extract, analyze and allocate commands. Extract takes a case plus CAD adapter. Analyze and allocate accept a fully manual case or a versioned snapshot.')
add('runtime','dispatch','Command dispatcher','Backend service','cli.py','Load CAD bindings only for extract. Route manual cases and snapshots through shared validation. Translate expected domain failures into structured outcomes and stable process exit codes.')
add('runtime','adapter-port','Adapter boundary','API','adapters/contract.py','Accept bound dimension identifiers and return extraction records. SOLIDWORKS uses an in-process adapter. FreeCAD runs its exporter inside the CAD Python runtime and writes a JSON record array. The CLI runs independently of CAD in replay.')

add('contracts','case','Case specification','Storage artifact','case.py','Versioned JSON with logical dimension IDs, signed coefficients, source declarations, model conditions, candidate options and optional objective. v0.1 evaluates one named functional chain by default. Joint evaluation is conditional on the first real assembly sharing an adjustable callout across requirements.')
add('contracts','manual','Manual dimensions','Storage artifact','case.py','Explicit nominal length and lower and upper signed deviations, with units. A drawing-only tolerance can be entered manually with a source reference.')
add('contracts','requirements','Functional requirements','Annotation','case.py','Each requirement has a stable ID and at least one declared clearance limit: minimum, maximum, or both. If both are present, reject reversed limits. The engineer also specifies the temperature interval and expansion coefficients. The reference temperature is explicit. The program has no default clearance, material or operating range.')
add('contracts','options','Candidate drawing options','Storage artifact','case.py','Each option identifies one permitted signed tolerance interval. Unchanged callouts stay at baseline. Key choices by the specific dimension/callout and applicable drawing revision or configuration. Distinct callouts on one drawing get independent options. Occurrences of the same callout share a choice, while their manufactured sizes can vary independently.')
add('contracts','objective','Declared objective','Annotation','case.py','Set a comparable unit for every score in an additive objective. Store its basis as a synthetic penalty or a quoted cost with context. Without a comparable objective, the result returns feasible choices without a recommendation.')

add('resolve','parse','Schema and version check','Validation','case.py','Identify input kind and schema version. Reject malformed JSON, unsupported versions, non-finite values, duplicated identifiers and invalid intervals before evaluation.')
add('resolve','normalize','Unit normalization','Data processor','case.py','Convert lengths and deviations to mm, absolute temperatures to °C and coefficients to K⁻¹. Retain source values and original units. Reject unknown or dimensionally incompatible units.')
add('resolve','precision','Numerical representation','Annotation','case.py','Use finite decimal strings in persisted physical quantities and exact rational arithmetic for the linear reference model. Convert CAD doubles via deterministic round-trip decimal text before applying unit conversions. Preserve the source value; apply formatting only in the terminal.')
add('resolve','merge','Resolve dimensions','Data processor','case.py','Join manual and CAD records by logical ID, verify physical dimension identities and choose the declared tolerance source. Flag a manual/CAD discrepancy when both exist. Resolve all required values or return an input diagnostic.')
add('resolve','snapshot','Resolved snapshot','Storage artifact','snapshot.py','Store every normalized input, version, source and assumption needed for deterministic replay. Save a complete snapshot only after validation, using an atomic replacement. The analyzer validates saved snapshots on read.')
add('resolve','replay','Replay validation','Validation','snapshot.py','Validate a resolved snapshot directly and pass the canonical problem to the requested operation. Replay never re-resolves CAD references or fetches external data.')

model('analysis','compile','Compile signed chain','analysis.py','Combine repeated references to the same physical dimension before propagation. References to distinct manufactured occurrences can vary independently, even when they share a dimension callout.',{method:'Group by physical variable identity and sum signed coefficients. Preserve each distinct callout identity for option assignment.', validation:'A dimension referenced as +1 and −1 contributes exactly zero.'})
model('analysis','expand','Expand drawing limits','analysis.py','Expand the lower and upper drawing limits separately using the linear factor for that part and temperature.',{formula:'L(T) = (L₀ + δ) [1 + α(T − T₀)]',assumptions:'Free expansion; fixed α for each dimension; a common uniform temperature; positive expansion factor over the stated interval.',edgeCases:'Reject nonpositive scale factors and unsupported thermal models. A fixed-temperature case uses one endpoint.'})
model('analysis','interval','Propagate signed bounds','analysis.py','Propagate each coefficient against both expanded drawing limits and sum interval endpoints.',{formula:'g_min(T) = Σ min(aᵢ Lᵢ,low(T), aᵢ Lᵢ,high(T)); g_max(T) = Σ max(aᵢ Lᵢ,low(T), aᵢ Lᵢ,high(T))', validation:'Compare against independent corner enumeration for small chains; cover negative, zero and repeated coefficients.'})
model('analysis','endpoints','Temperature envelope','analysis.py','Check both clearance bounds at both operating endpoints. For this model each bound is affine in the common temperature, so endpoint evaluation covers the interval.',{method:'Reduce endpoint results to the global lower and upper bounds and record each controlling endpoint. Represent tied endpoints consistently.',limitations:'Temperature gradients, constrained expansion, deformation and temperature-dependent α require separate model validation.'})
model('analysis','clearance-gate','Clearance constraint','analysis.py','Compare the full-range envelope against each declared side. Return signed margins and limiting conditions only for declared constraints. Preserve physical bounds on both sides.',{formula:'m_lower = g_min − g_required,min; m_upper = g_required,max − g_max',edgeCases:'Touching a limit passes with exact arithmetic on canonical inputs. A quantized CAD observation can still carry input uncertainty; exact arithmetic does not remove it.'})
model('analysis','bound-trace','Controlling stack-up','analysis.py','At the lower and upper controlling cases, retain each physical dimension ID, callout ID, signed coefficient, chosen drawing limit, expanded length and signed contribution. Each trace sums to its reported clearance bound.',{method:'Use the evaluator’s coalesced terms and tie policy. Label the controlling temperature independently for each physical bound.'})

model('allocation','options-expand','Candidate combinations','allocation.py','Form the Cartesian product of choices by callout identity. Apply each choice to every occurrence that shares the callout.',{method:'Enumerate candidates in a defined order. Track the total and evaluated counts. If a runtime budget halts the search, return incomplete.'})
model('allocation','candidate-check','Candidate evaluator','allocation.py','Build a candidate copy of the validated problem and invoke the same evaluator used for baseline analysis.',{validation:'Re-evaluating the selected candidate as an ordinary standalone analysis returns identical bounds.'})
model('allocation','ranking','Objective and ranking','allocation.py','Rank feasible candidates by the declared comparable objective and report ties. With no comparable ranking, return feasible choices; if search is incomplete mark any best-so-far candidate provisional.',{method:'Apply feasibility before objective. Preserve objective units and source. Do not treat a zero-valued missing score as free.', alternatives:'Consider MILP when measured scale warrants it and the objective and constraints admit a linear formulation. Verify against exhaustive reference cases.'})
model('allocation','closest','Closest tested candidate','allocation.py','When no tested candidate passes, retain the tested candidate with the smallest worst declared violation in mm. Keep this diagnostic separate from recommendations.',{formula:'v = max(0, max over declared margins of −m)',method:'Compare by violation first, then stable candidate order for ties. Report requirement IDs, declared margins and governing temperatures. An interrupted search labels the result closest evaluated so far. Zero evaluated candidates yields no diagnostic candidate.'})
add('allocation','joint-scope','Joint allocation scope gate','Validation','real assembly review','If the first real assembly shares an adjustable callout across affected functional requirements, apply each candidate assignment once and evaluate all affected named chains. Require all to pass and report the limiting requirement and side. Otherwise report single-chain scope explicitly.',{priority:'P1',status:'proposed'})
add('cad','binding-trial','Binding authoring trial','Validation','adapters/solidworks.py','Observe how an engineer locates occurrence paths, dimension identifiers and configurations on the first real assembly. If that is the bottleneck, prototype read-only selection or discovery that prints the binding and resolved source.',{priority:'P2',status:'proposed'})

add('pack','result','Structured result','Storage artifact','report.py','Versioned result distinguishes baseline and candidate drawing limits. Include requirement ID and evaluation scope, physical bounds, declared signed margins, controlling temperatures, signed term contributions, changed callouts, net margin recovery, objective basis, and search status and counts.')
add('pack','change-trace','Drawing change explanation','Data processor','report.py','Show baseline and selected or diagnostic callout limits and the change in each declared margin. For attribution, compare signed terms at the same temperature and side. Show governing-temperature change separately; do not attribute the entire margin shift to a callout when different temperatures control.')
add('pack','errors','Diagnostics and exit codes','API','cli.py','Distinguish invalid input, unavailable CAD, failed extraction, proven infeasibility, incomplete search and internal failure. Provide relevant source IDs and recovery guidance. Reserve success codes for successful completion per command contract.')
add('pack','terminal','Terminal and JSON output','Frontend component','report.py','Render the same structured result in terminal or JSON. Route diagnostics consistently. Keep machine-readable quantities and units independent of display precision.')

gate('verify','case-test','Contract and replay tests','G01','Manual and CAD-shaped fixtures resolve to equivalent normalized numbers. The saved snapshot replays without a CAD dependency.','Reject the contract change or supply an explicit compatible schema revision.','Versioned cases and expected JSON.')
gate('verify','numeric-test','Numerical verification','G02','Hand results and independent corner enumeration match the evaluator. Cover symmetric, asymmetric, unilateral, zero-width and repeated-variable cases.','Inspect units, endpoint selection and interval arithmetic before continuing.','Expected baseline envelope 0.041143 to 0.158927 mm.')
gate('verify','allocation-test','Allocation verification','G03','The reference search finds the bore-only option at penalty 1. Exercise ties, unavailable objectives, infeasible and incomplete searches.','Check candidate application and objective behavior.','Golden candidate report and status cases.')
gate('verify','cad-test','Live CAD integration','G04','Named dimensions resolve in the intended occurrence configurations. After a rebuild a CAD change appears in a new snapshot; replay of the old snapshot remains stable.','Keep support provisional until a real installation passes.','Recorded CAD version, fixture and extracted snapshots.')
gate('verify','release-test','Packaging and release','G05','Install the Python package in a clean no-CAD environment and reproduce a result. Independently run SOLIDWORKS extraction on a supported desktop and review one real case.','Publish only support that has passed its corresponding checks.','Installation instructions and verification evidence.')
gate('verify','explanation-test','Actionable report check','G06','From the report alone, identify the failed requirement and side, the signed terms that drove each bound, and the permitted callout change and recovered margins. Cover min-only, max-only, two-sided, no-feasible and interrupted searches.','Correct missing traces, false recommendations and misleading contribution attribution before release.','Verified baseline, feasible change and closest-tested result examples.')

add('research','supplier-data','Supplier evidence','External dataset','future study','Permissioned quotes or process measurements, with supplier, process, part, material, quantity and tolerance context.',{priority:'P3',status:'proposed',classification:'Optional'})
add('research','cost-model','Cost estimation study','Scientific model','future study','Compare a cost model against a simple baseline using held-out jobs and an uncertainty policy. Approve a model score only if it is useful within its validated domain.',{priority:'P3',status:'proposed',classification:'Optional',review:{decision:'Data dependent',foundation:'Supervised regression on supplier quote outcomes.',availability:'Representative data have not been established.',value:'Potential ranking input.',difficulty:'Dataset coverage, cross-job generalization and uncertainty.',validationStatus:'Not evaluated',uncertainty:'Unknown until representative held-out jobs exist.'}})

const connections: Connection[] = []
function wire(source: string, target: string, label: string, payload: string, format: string, failure: string,
  kind: Connection['kind'] = 'Data flow', units = '', validation = 'Validate the receiving contract before use.') {
  const id = 'edge-' + source + '-' + target
  const from = components.find(item=>item.id===source)
  const to = components.find(item=>item.id===target)
  if (!from || !to) throw new Error(`Unknown connection endpoint for ${id}`)
  const protocol = format === 'COM' ? 'Windows COM API' : format.includes('JSON') ? 'Local JSON file' : 'In-process Python call'
  connections.push({ id,source,target,label,payload,format,protocol,failure,kind,units,validation,
    description:`${from.name} → ${to.name}`, dependencies:[],
  })
  const output = {...newVariable(),name:label,type:format,unit:units,description:payload,componentId:target}
  from.outputs.push(output)
  to.inputs.push({...output,componentId:source})
  return id
}

wire('cli','dispatch','Command request','Operation, input path, optional adapter and output destination.','Command arguments','Return usage error before reading CAD.','Request')
wire('dispatch','adapter-port','SOLIDWORKS extract request','Binding list and active assembly selector. Extract only.','Adapter request','Report an unavailable session before attempting bindings.','Request')
wire('adapter-port','bindings','Read bindings','Explicit identifiers for the occurrence and named dimension.','Adapter request','Reject missing or ambiguous bindings.','Request')
wire('solidworks','bindings','Active assembly','Active document type and assembly occurrence data.','COM','Require the intended assembly to be active and resolved.','Data flow','', 'Reject suppressed or unresolved required occurrences.')
wire('bindings','annotations','Resolved dimension reference','Occurrence, referenced configuration and native dimension identifier.','COM','Report the failed lookup and retain the logical ID.','Data flow','', 'Verify configuration against the assembly occurrence.')
wire('annotations','extraction','Dimensional fields','Native nominal, tolerance type, status and available deviations.','Typed adapter data','Leave unsupported deviations absent and record why.','Data flow','Source length units')
wire('extraction','merge','CAD extraction record','Source document state, occurrence, configuration, units, nominal and supported offsets.','Typed adapter record','Missing required measurements stop snapshot creation.','Data flow','Source length units')
wire('secondary-cad','extraction','FreeCAD nominal export','One versioned outcome per explicit binding, with mm, observed provenance and unavailable tolerance evidence.','Extraction record array JSON','Reject unqualified objects and non-length properties.','Data flow','mm')
wire('dispatch','extraction','FreeCAD record import','Read the exported record array for the validated case.','Extraction record array JSON','Reject records that do not match the case bindings.','Request')
wire('manual','case','Manual dimension values','Logical IDs, nominal lengths, lower and upper offsets and declared origin.','Case JSON v1','Require an explicit valid unit and tolerance for each manual dimension.','Configuration','Declared units')
wire('requirements','case','Engineering constraints','Signed functional chain, allowable clearance, expansion coefficients, temperature assumptions.','Case JSON v1','Reject absent engineering requirements.','Configuration','Length, °C, K⁻¹')
wire('options','case','Drawing options','Discrete candidate IDs, interval deviations and configuration-aware callout identity.','Case JSON v1','Reject duplicate option keys and ambiguous shared choices.','Configuration','Declared length units')
wire('objective','case','Ranking policy','Comparable score unit and basis, optional score per option.','Case JSON v1','An absent objective permits feasibility reporting without a winner.','Configuration','Declared cost or penalty unit')
wire('case','parse','Versioned case','Full authoring contract with manual and/or CAD bindings.','Case JSON v1','Reject unknown versions and field-level errors.','Data flow')
wire('dispatch','parse','Validate case input','A manual case for analyze or allocate, or a bound case for extract.','Case JSON v1','Reject operation and input combinations the CLI cannot execute.','Request')
wire('parse','adapter-port','Validated CAD bindings','Typed binding records passed only on extract, before any CAD lookups.','Adapter request','Reject unknown bindings before contacting CAD.','Control')
wire('parse','normalize','Typed case','Validated source values and recognized physical quantities.','Typed case','Report field path for invalid data.','Data flow')
wire('normalize','merge','Normalized case','Canonical length, temperature and coefficient values plus raw provenance.','Typed case','Reject incompatible dimensions or invalid ranges.','Data flow','mm, °C, K⁻¹')
wire('precision','normalize','Precision and units policy','Decimal input and exact rational conversion policy.','Numerical policy','Refuse quantities outside the supported unit or numeric format.','Configuration')
wire('merge','snapshot','Fully resolved problem','All inputs, resolved tolerance origin, source identity and case version.','Snapshot JSON v1','Abort the write on an unresolved required field.','Derived product','mm, °C, K⁻¹')
wire('snapshot','replay','Replay snapshot','Versioned frozen input document supplied to analyze or allocate.','Snapshot JSON v1','Refuse unsupported versions and incomplete snapshots.','Data flow')
wire('dispatch','replay','Offline analysis request','Evaluate or allocate using a saved snapshot or the normalized in-memory manual equivalent.','Command request','Reject replay arguments that require a live CAD session.','Request')
wire('replay','compile','Validated problem','Canonical signed chain and baseline drawing bounds.','Resolved Python object','Reject impossible identities and non-finite values.','Data flow','mm, °C, K⁻¹')
wire('compile','expand','Coalesced physical variables','Signed coefficients and unique physical dimensions.','Typed chain','Reject conflicting definitions for the same physical dimension.','Data flow','mm')
wire('expand','interval','Expanded drawing bounds','Lower and upper actual lengths at each operating endpoint.','Endpoint array','Reject nonpositive expansion factors.','Derived product','mm, °C')
wire('interval','endpoints','Pointwise clearance intervals','Minimum and maximum clearance at each evaluated temperature.','Typed endpoint bounds','Check both bounds and keep controlling temperatures.','Derived product','mm, °C')
wire('endpoints','clearance-gate','Operating envelope','Global lower and upper clearance bounds and corresponding endpoint temperatures.','Typed envelope','Expect ordered finite bounds and retain controlling assumptions.','Derived product','mm, °C')
wire('endpoints','bound-trace','Controlling bound cases','Controlling temperatures, sides and expanded signed terms.','Typed bound cases','Reject trace totals that do not reconstruct the bounds.','Derived product','mm, °C')
wire('bound-trace','change-trace','Signed dimensional contributions','Term-level evidence for baseline and reported candidate bounds.','Trace records','Use the same temperature for contribution comparisons.','Data flow','mm, °C')
wire('clearance-gate','result','Baseline bounds and margin','Feasibility comparison, declared signed margins, and limiting endpoints.','Analysis result','An infeasible baseline remains valid input for allocation.','Data flow','mm, °C')
wire('replay','options-expand','Permitted choices','Declared options indexed by callout identity, fixed dimensions, objective basis.','Resolved Python object','Reject inconsistent candidate groups.','Data flow')
wire('options-expand','candidate-check','Candidate drawing limits','Apply one complete option combination to the resolved snapshot.','Candidate object','Track combination count and report incomplete search explicitly.','Data flow','mm')
wire('candidate-check','compile','Evaluate candidate','Same typed analysis input with the candidate drawing bounds.','Resolved Python object','An internal evaluator error aborts the search with structured diagnostics.','Request')
wire('clearance-gate','candidate-check','Candidate feasibility','Candidate envelope and declared signed margins from the shared evaluator.','Analysis result','Preserve an infeasible candidate outcome without treating it as an execution error.','Response','mm, °C')
wire('candidate-check','ranking','Candidate outcomes','Candidate IDs, feasibility evidence, score and search completion state.','Candidate stream','No global optimum claim if the search is incomplete.','Data flow')
wire('candidate-check','closest','Declared violations','Evaluated candidate IDs and signed margins, grouped by requirement and side.','Candidate stream','Zero evaluated candidates yields no closest candidate.','Data flow','mm')
wire('closest','result','Infeasibility diagnostic','Least violating tested candidate, margins, governing cases and completeness qualifier.','Diagnostic result','Never present a failing candidate as a recommended allocation.','Data flow','mm, °C')
wire('ranking','change-trace','Reported feasible choice','Selected permitted callout limits when a ranked choice is available.','Candidate result','Only explain a selected option when the result identifies one.','Data flow')
wire('closest','change-trace','Reported diagnostic choice','Closest tested callout limits when no tested candidate passes.','Diagnostic result','Mark all reported diagnostic changes as still failing.','Data flow')
wire('change-trace','result','Callout changes and margin delta','Baseline and candidate limits, declared margin changes and same-condition attribution.','Explanation record','Flag changed controlling conditions explicitly.','Data flow','mm, °C')
wire('ranking','result','Allocation result','Feasible options, ties, score inputs and checked-versus-total counts.','Allocation result','Return infeasible only after exhaustive search finds no feasible choices.','Data flow')
wire('dispatch','errors','Command failure','Validation, adapter and execution diagnostics with context.','Diagnostic record','Map expected failures to documented process outcomes.','Response')
wire('errors','terminal','Diagnostic output','Stable error code, affected field or source and concise recovery instruction.','Diagnostic record','Keep stderr distinct from machine-readable stdout.','Data flow')
wire('result','terminal','Render output','Versioned result object with units and assumption provenance.','Result JSON v1','Report output I/O failure explicitly.','Data flow')
wire('snapshot','case-test','Replay fixture','Manual and CAD-shaped inputs resolving to the same benchmark.','Snapshot fixture JSON','Compare normalized quantities and verify provenance separately.','Validation')
wire('interval','numeric-test','Independent bound check','Calculated signed bounds for hand and corner-enumeration fixtures.','Test observations','A mismatch blocks the numerical validation gate.','Validation')
wire('ranking','allocation-test','Search acceptance check','Expected candidate, completion state, ties and absent-objective cases.','Test observations','A ranking or completeness error blocks allocation validation.','Validation')
wire('extraction','cad-test','CAD parity check','Two extracted snapshots before and after a controlled CAD edit and rebuild.','Test observations','Record source configuration and compare with the planned numerical delta.','Validation')
wire('case-test','release-test','Contract evidence','Validated snapshot replay on a clean environment.','Gate record','Gate remains unevaluated without the test evidence.','Validation')
wire('numeric-test','release-test','Numerical evidence','Independent interval and temperature results.','Gate record','Release only after the required model tests pass.','Validation')
wire('allocation-test','release-test','Allocation evidence','Reference ranking result and failure behavior.','Gate record','Withhold allocation support if acceptance fails.','Validation')
wire('cad-test','release-test','Integration evidence','Tested CAD version, supported annotation types and replay evidence.','Gate record','Advertise only tested CAD capability.','Validation')
wire('terminal','release-test','CLI evidence','Machine-readable result, diagnostic form and observed exit status from a clean environment.','Test observations','Block release if the documented CLI contract differs from the observed result.','Validation')
wire('result','explanation-test','Report-only acceptance','Failed requirement, signed terms, permitted changes and margin recovery.','Result JSON v1','A reviewer must reproduce the stated decision from the report.','Validation')
wire('explanation-test','release-test','Explanation evidence','Verified actionable report fixtures and result review.','Gate record','Block release until the report answers the decision questions.','Validation')
wire('cad-test','binding-trial','Binding workflow evidence','Observed binding steps, wrong-configuration failures and time spent locating identifiers.','Review observations','Defer discovery unless the CAD trial identifies binding authoring as a bottleneck.','Validation')
wire('joint-scope','candidate-check','Conditional joint evaluation','One callout assignment applied to all affected named requirements.','Scope decision','Single-chain mode records its scope; joint mode requires every affected requirement to pass.','Control')
wire('supplier-data','cost-model','Training evidence','Permissioned quotes with meaningful part, process and supplier context.','Future dataset','Defer if measurement or context coverage is insufficient.','Data flow')
wire('cost-model','ranking','Optional estimated objective','Validated cost estimate and uncertainty for ranking only. Outside v0.1.','Future objective record','Reject estimates outside the validated domain.','Validation')

const stages = [
  ['stage-runtime','Runtime boundaries','Define the local package, command entry points, dependency directions, optional CAD adapter boundary and replay path.','A manual test fixture can enter the CLI without loading CAD dependencies.'],
  ['stage-contracts','Input & output contracts','Define case JSON, extraction fields, normalized snapshot, result and error contracts. Record expected fixture values before implementing the solver.','Manual and CAD-shaped fixtures resolve consistently. Invalid requirements fail with precise diagnostics.'],
  ['stage-analysis','Deterministic evaluator','Implement signed intervals, repeated-variable handling, thermal endpoints and functional constraints.','Hand solution and independent corner enumeration agree, including asymmetric and unilateral limits.'],
  ['stage-allocation','Allocation & reporting','Reuse the evaluator across discrete drawing options and report margins, infeasibility, ranking and completion.','The report alone identifies the failed requirement, signed contributors and the permitted callout change with its measured margin recovery. Diagnostic results pass exhaustive, interrupted and zero-tested cases.'],
  ['stage-cad','SOLIDWORKS adapter','Qualify the connector against the frozen extraction contract. Run a small CAD API spike earlier to test named dimensions and configurations.','A live two-part fixture matches the manual result. A controlled CAD edit changes the fresh snapshot and leaves the previous snapshot replayable.'],
  ['stage-verify','Cross-system verification','Run the CLI, contract and numerical tests without CAD. Repeat adapter integration on the supported version with captured artifacts.','A clean environment reproduces the same result. Every reported support claim has corresponding evidence.'],
  ['stage-release','Engineering review','Use one real assembly and ship documentation, source examples and a replayable result.','An engineer can identify the failed requirement, controlling dimensions and what changed from the report alone. Decide whether shared callouts require joint evaluation before releasing support for that assembly.'],
] as const

const decisionSteps: ComponentStep[] = []
type ComponentStep = { componentId: string; caption: string; transition: string; connectionIds: string[] }
const deliverables = [
  ['cli','dispatch','adapter-port'],
  ['case','extraction','snapshot','result','errors'],
  ['compile','expand','interval','endpoints','clearance-gate'],
  ['options-expand','candidate-check','ranking','closest','bound-trace','change-trace','terminal'],
  ['bindings','annotations','cad-test'],
  ['case-test','numeric-test','allocation-test','explanation-test'],
  ['release-test','joint-scope','binding-trial'],
]
stages.forEach(([id,name,description,acceptance],index) => {
  add('build',id,name,'Infrastructure','Segment '+(index+1),description)
  const component = components.at(-1)!
  component.gate = { code:'S'+(index+1),stage:name,acceptance,failure:'Resolve the failed criterion before accepting this segment.',output:'Reviewable implementation and evidence.',result:'Not evaluated' }
  const previous = stages[index-1]
  if (previous) component.dependencies.push(previous[0])
  const connectionIds = previous ? [wire(previous[0],id,'Segment handoff','Accepted implementation and verification evidence.','Build handoff','Keep dependent work provisional until acceptance.','Deployment')] : []
  for (const deliverable of deliverables[index]) {
    wire(id,deliverable,'Implementation scope','Component delivered or qualified in this segment.','Work item','Record incomplete evidence before marking the segment complete.','Deployment')
  }
  decisionSteps.push({ componentId:id,caption:description,transition:'Accepted handoff',connectionIds })
})

export const initialArchitecture = architectureSchema.parse({
  schemaVersion:1, architectureVersion:'0.1.1', title:'StackOpt', pipelineRevision:1, modelRevision:1,
  groups, components, connections, decisionSteps, layout:{}, viewSettings:{ ...defaultView,view:'system' },
})
