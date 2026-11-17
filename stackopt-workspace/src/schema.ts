import { z } from 'zod'

export const categories = ['External dataset', 'Data processor', 'Scientific model', 'Algorithm', 'Backend service', 'API', 'Frontend component', 'Storage artifact', 'Infrastructure', 'Validation', 'Annotation'] as const
export const statuses = ['proposed', 'planned', 'in_progress', 'implemented', 'validated', 'tbd'] as const
export const classes = ['Architecture', 'Catalog evidence', 'Observation', 'Predicted', 'Interpretation', 'Derived', 'Assumption', 'Simulation', 'Decision', 'Optional', 'Excluded'] as const
export const kinds = ['Data flow', 'Request', 'Response', 'Control', 'Validation', 'Deployment', 'Derived product', 'Configuration', 'Provenance'] as const
export const views = ['system', 'pipeline', 'models', 'runtime', 'decision'] as const
export type View = typeof views[number]
export const pipelineLenses = ['complete', 'global', 'regions', 'regional', 'terrain', 'science', 'publication'] as const
export type PipelineLens = typeof pipelineLenses[number]
export const pipelineLayouts = ['pipeline-complete', 'pipeline-global', 'pipeline-regions', 'pipeline-regional', 'pipeline-terrain', 'pipeline-science', 'pipeline-publication'] as const
export const modelLenses = ['complete','intervals','thermal','requirements','allocation','ranking','research','verification'] as const
export type ModelLens = typeof modelLenses[number]
const modelLayouts = modelLenses.map(lens => `models-${lens}` as const)
export type LayoutKey = View | typeof pipelineLayouts[number] | typeof modelLayouts[number]
export const researchDecisions = ['Adopted','Proposed','Research required','Data dependent','Deferred','Rejected'] as const
export const gateResults = ['Not evaluated', 'Passed', 'Failed', 'Not applicable'] as const

const str = z.string()
const id = str.regex(/^[a-zA-Z][a-zA-Z0-9_-]*$/, 'Use a letter followed by letters, numbers, underscores or hyphens.')
const label = str.trim().min(1)
const httpUrl = z.union([z.literal(''), z.url({ protocol: /^https?$/ })])
const ref = z.object({ label, url: httpUrl, locator: str, evidenceType: str.optional(), verification: str.optional(), notes: str.optional() })
const variable = z.object({ name: label, type: str, unit: str, description: str, componentId: z.union([id, z.literal('')]), required: z.boolean(), defaultValue: str, validRange:str.optional(), classification:z.enum(classes).optional(), availability:str.optional(), limitations:str.optional() })
const parameter = z.object({ name: label, type: str, unit: str, defaultValue: str, description: str, constraints: str, symbol:str.optional(), source:str.optional(), scientificStatus:str.optional(), provenance: z.enum(['Assumption', 'Observed input', 'Derived', 'Simulated', 'TBD']) })
const algorithm = z.object({ name: str, family: str, description: str, method: str, alternatives: str, complexity: str, limitations: str, validation: str, formula: str, pseudocode: str, implementation: str, variables:str.optional(), assumptions:str.optional(), edgeCases:str.optional() })
const dataset = z.object({ mission: str, product: str, provider: str, dataType: str, format: str, resolution: str, crs: str, coverage: str, temporal: str, limitations: str, availability: str, verification: str, instrument: str.optional(), processingLevel: str.optional(), accessMethod: str.optional() })
const gate = z.object({ code: str, stage: str, acceptance: str, failure: str, result: z.enum(gateResults), output: str })
const review = z.object({ decision:z.enum(researchDecisions), foundation:str, availability:str, value:str, difficulty:str, validationStatus:str, uncertainty:str })
const component = z.object({
  id, name: label, groupId: id, category: z.enum(categories), classification: z.enum(classes),
  purpose: str, description: str, technology: z.array(str), priority: z.enum(['P0','P1','P2','P3']), status: z.enum(statuses),
  owner: str, module: str, notes: str, risks: str, references: z.array(ref), dependencies: z.array(id),
  inputs: z.array(variable), outputs: z.array(variable), parameters: z.array(parameter),
  algorithm: algorithm.optional(), dataset: dataset.optional(), gate: gate.optional(), modelFamily:id.optional(), review:review.optional(),
})
const connection = z.object({
  id, source: id, target: id, label, kind: z.enum(kinds), payload: str,
  format: str, protocol: str, description: str, validation: str, dependencies: z.array(id),
  units: str.optional(), spatialReference: str.optional(), resolution: str.optional(), requiredMetadata: str.optional(), failure: str.optional(),
})
const group = z.object({ id, name: label, summary: str, description: str, tone: z.enum(['data','neutral','decision','constraint']), phase: z.enum(['offline','runtime','assurance']) })
const point = z.object({ x: z.number().min(-100000).max(100000), y: z.number().min(-100000).max(100000) })
const viewport = z.object({ x: z.number(), y: z.number(), zoom: z.number().min(.12).max(2) })
export const viewportSchema = viewport
export const viewSettingsSchema = z.object({
  view: z.enum(views), expanded: z.array(id), focus: z.string(), overviewAllLinks: z.boolean().optional(),
  category: z.union([z.enum(categories), z.literal('')]), status: z.union([z.enum(statuses), z.literal('')]),
  viewport: viewport.optional(), pipelineLens: z.enum(pipelineLenses).optional(), pipelineAllLinks: z.boolean().optional(), modelLens:z.enum(modelLenses).optional(), modelAllLinks:z.boolean().optional(),
})
export const architectureSchema = z.object({
  schemaVersion: z.literal(1), architectureVersion: label, title: label, pipelineRevision: z.literal(1).optional(), modelRevision:z.literal(1).optional(),
  groups: z.array(group).min(1), components: z.array(component), connections: z.array(connection),
  decisionSteps: z.array(z.object({ componentId: id, caption: label, transition: str, connectionIds: z.array(id) })),
  layout: z.partialRecord(z.enum([...views,...pipelineLayouts,...modelLayouts]), z.record(z.string(), point)),
  viewSettings: viewSettingsSchema,
}).superRefine((doc, ctx) => {
  const error = (message: string) => ctx.addIssue({ code: 'custom', message })
  const ids = (records: { id: string }[], name: string) => {
    const unique = new Set(records.map(item => item.id))
    if (unique.size !== records.length) error(`Duplicate ${name} ID.`)
    return unique
  }
  const groups = ids(doc.groups, 'group')
  const nodes = ids(doc.components, 'component')
  const edges = ids(doc.connections, 'connection')
  const checkNode = (key: string, owner: string) => {
    if (!nodes.has(key)) error(`${owner} references missing component ${key}.`)
  }
  for (const item of doc.components) {
    if (!groups.has(item.groupId)) error(`${item.name} references missing group ${item.groupId}.`)
    if (item.modelFamily && !groups.has(item.modelFamily)) error(`${item.name} references missing model family ${item.modelFamily}.`)
    item.dependencies.forEach(key => checkNode(key, item.name))
    for (const entry of [...item.inputs, ...item.outputs]) if (entry.componentId) checkNode(entry.componentId, item.name)
  }
  for (const edge of doc.connections) {
    checkNode(edge.source, edge.label)
    checkNode(edge.target, edge.label)
    if (edge.source === edge.target) error(`${edge.label} connects a component to itself.`)
    edge.dependencies.forEach(key => checkNode(key, edge.label))
  }
  for (const step of doc.decisionSteps) {
    checkNode(step.componentId, 'Build sequence')
    for (const key of step.connectionIds) if (!edges.has(key)) error(`Unknown walkthrough connection ${key}.`)
  }
  if (new Set(doc.decisionSteps.map(step => step.componentId)).size !== doc.decisionSteps.length) error('Duplicate build sequence step.')
  for (const key of doc.viewSettings.expanded) if (!groups.has(key)) error(`Unknown expanded group ${key}.`)
  if (doc.viewSettings.focus && !groups.has(doc.viewSettings.focus)) error('Unknown focused group.')
  for (const positions of Object.values(doc.layout)) {
    for (const key of Object.keys(positions ?? {})) {
      if (!nodes.has(key) && !(key.startsWith('group:') && groups.has(key.slice(6)))) error(`Unknown layout item ${key}.`)
    }
  }
})
export type Architecture = z.infer<typeof architectureSchema>
export type Component = z.infer<typeof component>
export type Connection = z.infer<typeof connection>
export type Group = z.infer<typeof group>
export type Variable = z.infer<typeof variable>
export type Parameter = z.infer<typeof parameter>
export type ModelReview = z.infer<typeof review>
export type Algorithm = z.infer<typeof algorithm>
export type Gate = z.infer<typeof gate>
export type Dataset = z.infer<typeof dataset>
export type Reference = z.infer<typeof ref>
export type Point = z.infer<typeof point>
export type ViewSettings = z.infer<typeof viewSettingsSchema>

export const emptyAlgorithm: Algorithm = {
  name: '', family: '', description: '', method: '', alternatives: '', complexity: '',
  limitations: '', validation: '', formula: '', pseudocode: '', implementation: '',
}
export const emptyDataset: Dataset = {
  mission: '', product: '', provider: '', dataType: '', format: '', resolution: '', crs: '',
  coverage: '', temporal: '', limitations: '', availability: '', verification: '',
}
export const newVariable = (): Variable => ({ name: 'New variable', type: '', unit: '', description: '', componentId: '', required: true, defaultValue: '' })
export const newParameter = (): Parameter => ({ name: 'New parameter', type: '', unit: '', defaultValue: '', description: '', constraints: '', provenance: 'TBD' })
export const newComponent = (id: string, groupId: string, category: Component['category'], name: string): Component => ({
  id, groupId, name, category, classification: 'Architecture', purpose: '', description: '',
  technology: [], priority: 'P0', status: 'proposed', owner: '', module: '', notes: '', risks: '',
  references: [], dependencies: [], inputs: [], outputs: [], parameters: [],
  ...(category === 'Algorithm' || category === 'Scientific model' ? { algorithm: { ...emptyAlgorithm } } : {}),
  ...(category === 'External dataset' ? { dataset: { ...emptyDataset } } : {}),
})
export const defaultView: ViewSettings = { view: 'system', expanded: [], focus: '', category: '', status: '' }
