import type { ModelLens } from './schema'

type ModelView = { label: string; description: string; rows: string[][]; open: string[] }
export const modelViews: Record<ModelLens,ModelView> = {
  complete: { label:'All models', description:'Hard constraints, physical bounds, allocation, and optional cost research.', rows:[['resolve','analysis','allocation','pack'],['verify','research']],open:[] },
  intervals: { label:'Dimensional bounds', description:'Signed worst-case dimensional limits with shared dimension identity.', rows:[['resolve','analysis','verify']],open:['analysis'] },
  thermal: { label:'Thermal expansion', description:'Free expansion of drawing bounds and the shared-temperature endpoint proof.', rows:[['contracts','analysis','verify']],open:['analysis'] },
  requirements: { label:'Functional requirements', description:'Clearance limits, controlling endpoints, signed margins and analytical scope.', rows:[['contracts','analysis','pack']],open:['analysis'] },
  allocation: { label:'Allocation', description:'Discrete search, independent candidate evaluation, and completion status.', rows:[['resolve','allocation','analysis','pack']],open:['allocation'] },
  ranking: { label:'Ranking', description:'Feasibility first, followed by comparable declared objective scores.', rows:[['analysis','allocation','pack']],open:['allocation'] },
  research: { label:'ML research', description:'A possible supplier cost model gated by evidence and held-out validation.', rows:[['research','allocation','verify']],open:['research'] },
  verification: { label:'Model verification', description:'Hand calculations, exhaustive corners, and deterministic snapshot replay.', rows:[['analysis','allocation','verify']],open:['verify'] },
}
