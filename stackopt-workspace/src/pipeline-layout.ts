import type { LayoutKey, PipelineLens, ViewSettings } from './schema'

export type PipelineRoute = 'above' | 'left-gutter' | 'right-gutter'
type Lens = { label: string; description: string; rows: string[][]; open: string[] }

export const systemRows = [
  ['runtime','cad','contracts','resolve'],
  ['verify','pack','allocation','analysis'],
  ['research'],
]

export const lenses: Record<PipelineLens,Lens> = {
  complete: { label:'All contracts', description:'From case inputs and CAD extraction through the replay snapshot and result.', rows:[['cad','contracts','resolve','runtime'],['verify','pack','allocation','analysis']],open:[] },
  global: { label:'Case authoring', description:'Versioned case specification, manual dimensions and explicit engineering inputs.', rows:[['contracts','resolve']],open:['contracts'] },
  regions: { label:'CAD extraction', description:'Document and occurrence identity, configuration, units, and supported tolerance sources.', rows:[['cad','contracts','resolve']],open:['cad'] },
  regional: { label:'Resolution', description:'Resolve logical dimensions, drawing options, provenance and units into typed records.', rows:[['contracts','resolve','analysis']],open:['resolve'] },
  terrain: { label:'Snapshot replay', description:'Save resolved inputs and run them through the same evaluator on a machine without CAD.', rows:[['resolve','runtime','analysis','pack']],open:['resolve','runtime'] },
  science: { label:'Result contract', description:'Baseline bounds, allocation status, evidence and structured diagnostics.', rows:[['analysis','allocation','pack','verify']],open:['pack'] },
  publication: { label:'Verification gates', description:'Reference fixtures, validation errors and live CAD acceptance checks.', rows:[['contracts','resolve','verify']],open:['verify'] },
}

export function layoutKey(settings: ViewSettings, pipeline?: number, models?: number): LayoutKey {
  if (settings.view === 'pipeline' && pipeline) return `pipeline-${settings.pipelineLens ?? 'complete'}`
  if (settings.view === 'models' && models) return `models-${settings.modelLens ?? 'complete'}`
  return settings.view
}
