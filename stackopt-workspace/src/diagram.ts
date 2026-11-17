import { modelViews } from './model-layout'
import { layoutKey, lenses, systemRows } from './pipeline-layout'
import type { PipelineRoute } from './pipeline-layout'
import type { Architecture, Component, Connection, Group, Point, ViewSettings } from './schema'

export const viewLabels = {
  system:'Complete system', pipeline:'Input & output contracts', models:'Engineering models',
  runtime:'Application runtime', decision:'Build sequence',
}

export const viewCopy = {
  system:'Sources, process boundaries, engineering analysis and verification.',
  pipeline:'Follow the interfaces from the original inputs to the result.',
  models:'Worst-case dimensional bounds, thermal assumptions, allocation and ranking.',
  runtime:'One local Python process, an optional CAD session and replayable files.',
  decision:'Follow the dependencies between implementation segments.',
}

export type Box = Point & {
  id: string; w: number; h: number; title: string; sub: string; tone: Group['tone'];
  kind: 'group' | 'component' | 'caption'; group?: Group; component?: Component; count?: number;
  expanded?: boolean; step?: number; regionHeight?: number; groupOrigin?: Point; subsystemNumber?: string;
}
export type Link = {
  id: string; source: string; target: string; label: string; links: Connection[];
  kind: Connection['kind']; tone?: 'trace'; lane?: number; route?: PipelineRoute; hideLabel?: boolean;
}
export const groupKey = (key: string) => 'group:' + key
const columnPitch = 314
const groupWidth = 218
const detailW = 186
const detailH = 54
const detailPitch = 68
const headH = 90
const runtimeRows = [systemRows[0],systemRows[1]]
const overviewEdges = new Map<string,{ label: string; route?: PipelineRoute }>([
  ['runtime>cad',{ label:'extract request' }],
  ['cad>resolve',{ label:'extracted dimensions',route:'above' }],
  ['contracts>resolve',{ label:'case specification' }],
  ['resolve>analysis',{ label:'replay inputs' }],
  ['resolve>allocation',{ label:'drawing options' }],
  ['allocation>analysis',{ label:'evaluate candidate' }],
  ['analysis>pack',{ label:'clearance bounds',route:'above' }],
  ['allocation>pack',{ label:'allocation result' }],
  ['pack>verify',{ label:'release evidence' }],
  ['research>allocation',{ label:'optional objective' }],
])
const numberTags = new Map(systemRows.flat().concat('build').map((id,index)=>[id,String(index+1).padStart(2,'0')]))
export const numberFor = (id: string) => numberTags.get(id) ?? '—'
function toneFor(item: Component, group: Group): Group['tone'] {
  if (item.classification === 'Assumption' || item.gate) return 'constraint'
  if (item.classification === 'Decision') return 'decision'
  return group.tone
}

function decideLayout(doc: Architecture, items: Component[], groups: Map<string, Group>, settings: ViewSettings) {
  const boxes: Box[] = []
  const links: Link[] = []
  const steps = doc.decisionSteps
  const visible = new Map(items.map(item => [item.id, item]))
  steps.forEach((step, index) => {
    const item = visible.get(step.componentId)
    if (!item) return
    const group = groups.get(item.groupId)!
    const row = Math.floor(index / 4)
    const col = row % 2 ? 3 - index % 4 : index % 4
    boxes.push({
      id: item.id, x: col * columnPitch, y: row * 169 + 70, w: groupWidth, h: 88,
      title: item.name, sub: item.technology.join(' · '), kind: 'component', group, component: item,
      tone: toneFor(item,group), step: index + 1, ...doc.layout.decision?.[item.id],
    })
  })
  const ids = new Set(boxes.map(box => box.id))
  const byId = new Map(doc.connections.map(edge => [edge.id, edge]))
  steps.slice(1).forEach((step, index) => {
    const prev = steps[index]
    if (!ids.has(prev.componentId) || !ids.has(step.componentId)) return
    const actual = doc.connections.filter(edge => edge.source === prev.componentId && edge.target === step.componentId)
    const backed = step.connectionIds.map(id => byId.get(id)).filter((edge): edge is Connection => Boolean(edge))
    const reached = new Set([prev.componentId])
    for (let pass = 0; pass < backed.length; pass++) {
      for (const edge of backed) if (reached.has(edge.source)) reached.add(edge.target)
    }
    if (reached.has(step.componentId) || actual.length) {
      const edges = reached.has(step.componentId) ? backed : actual
      links.push({ id: 'trace:' + step.componentId, source: prev.componentId, target: step.componentId,
        label: step.transition || edges[0].label, links: edges, kind: 'Control', tone: 'trace' })
    }
  })
  const used = new Set(links.flatMap(link => link.links.map(edge => edge.id)))
  for (const edge of doc.connections) {
    if (edge.id.startsWith('link-') && ids.has(edge.source) && ids.has(edge.target) && !used.has(edge.id)) {
      links.push({ id:edge.id,source:edge.source,target:edge.target,label:edge.label,links:[edge],kind:edge.kind,lane:1 })
    }
  }
  if (boxes.length && !settings.category && !settings.status) {
    boxes.unshift(caption('event','PACKAGE & CORE',0,20),caption('outcome','INTEGRATION & RELEASE',0,226))
  }
  return { boxes, links }
}
function caption(id: string, title: string, x: number, y: number): Box {
  return { id: 'caption:' + id, title, sub: '', x, y, w: 214, h: 18, kind:'caption', tone:'neutral' }
}

export function buildDiagram(doc: Architecture, settings: ViewSettings) {
  const groups = new Map(doc.groups.map(group => [group.id, group]))
  const items = doc.components.filter(item => (!settings.category || item.category === settings.category) && (!settings.status || item.status === settings.status))
  const onlyMatches = Boolean(settings.category || settings.status)
  if (settings.view === 'decision' && !settings.focus) return decideLayout(doc, items, groups, settings)
  const pipeline = settings.view === 'pipeline'
  const models = settings.view === 'models'
  const overview = !settings.focus && !settings.expanded.length && !onlyMatches && (settings.view === 'system' || settings.view === 'runtime')
  const allLinks = models ? settings.modelAllLinks : pipeline ? settings.pipelineAllLinks : settings.overviewAllLinks
  const rows = settings.focus ? [[settings.focus]] : pipeline ? lenses[settings.pipelineLens ?? 'complete'].rows :
    models ? modelViews[settings.modelLens ?? 'complete'].rows : settings.view === 'runtime' ? runtimeRows : systemRows
  const positions = doc.layout[layoutKey(settings,doc.pipelineRevision,doc.modelRevision)] ?? {}
  const boxes: Box[] = []
  const endpoints = new Map<string, string>()
  const byGroup = Map.groupBy(items, item => models ? item.modelFamily ?? item.groupId : item.groupId)
  let y = 58
  for (const [rowIndex,row] of rows.entries()) {
    if ((settings.view === 'system' || settings.view === 'runtime') && !settings.focus && !onlyMatches && !settings.expanded.length) {
      boxes.push(caption(String(rowIndex), ['CAD, CLI & INPUTS','ANALYSIS, OUTPUT & VERIFICATION','FUTURE RESEARCH'][rowIndex], 0, y-29))
    }
    let rowHeight = headH
    row.forEach((id,index) => {
      const group = groups.get(id)
      const children = byGroup.get(id) ?? []
      if (!group || (onlyMatches && !children.length)) return
      const key = groupKey(id)
      const origin = positions[key] ?? { x:index * columnPitch,y }
      const expanded = Boolean(settings.focus || onlyMatches || settings.expanded.includes(id))
      const local = children.map((item,i) => positions[item.id] ?? { x:16,y:65+i*detailPitch })
      const height = expanded ? Math.max(106,...local.map(pos=>pos.y+detailH+16)) : headH
      rowHeight = Math.max(rowHeight,height)
      boxes.push({ id:key,...origin,w:groupWidth,h:expanded ? 50 : headH,kind:'group',title:group.name,sub:group.summary,
        tone:group.tone,group,count:children.length,expanded,regionHeight:height })
      children.forEach((item,i) => {
        endpoints.set(item.id,expanded ? item.id : key)
        if (!expanded) return
        boxes.push({ id:item.id,x:origin.x+local[i].x,y:origin.y+local[i].y,w:detailW,h:detailH,kind:'component',
          title:item.name,sub:item.gate?.code ?? (item.technology.join(' · ') || item.category),tone:toneFor(item,group),group,component:item,groupOrigin:origin })
      })
    })
    y += rowHeight + 88
  }

  const pairs = new Map<string, Link>()
  const mainKinds: Connection['kind'][] = ['Data flow','Request','Response','Derived product','Configuration']
  for (const edge of doc.connections) {
    const source = endpoints.get(edge.source), target = endpoints.get(edge.target)
    if (!source || !target || source === target) continue
    const collapsed = source.startsWith('group:') || target.startsWith('group:')
    const overviewKey = source.slice(6)+'>'+target.slice(6)
    const primary = overview ? overviewEdges.get(overviewKey) : undefined
    if (overview && !allLinks && !primary && !edge.id.startsWith('link-')) continue
    if ((models || pipeline) && !allLinks && collapsed && !mainKinds.includes(edge.kind)) continue
    const key = collapsed ? source+'>'+target : edge.id
    const existing = pairs.get(key)
    if (existing) {
      existing.links.push(edge)
    } else {
      const bothGroups = source.startsWith('group:') && target.startsWith('group:')
      pairs.set(key,{ id:collapsed ? 'bundle:'+key : edge.id,source,target,label:primary?.label ?? edge.label,kind:edge.kind,links:[edge],
        route:primary?.route,hideLabel:!bothGroups || Boolean(overview && allLinks && !primary) })
    }
  }
  return { boxes,links:[...pairs.values()] }
}

export function switchSettings(settings: ViewSettings, view: ViewSettings['view'], _pipeline?: number, _models?: number): ViewSettings {
  const expanded = view === 'pipeline' ? lenses[settings.pipelineLens ?? 'complete'].open :
    view === 'models' ? modelViews[settings.modelLens ?? 'complete'].open : []
  return { ...settings,view,expanded,focus:'',viewport:undefined }
}

export function curve(link: Link, a: Box, b: Box, dual: boolean) {
  const cx = (n:Box) => n.x + n.w / 2
  const cy = (n:Box) => n.y + n.h / 2
  const dx = cx(b) - cx(a), dy = cy(b) - cy(a)
  const offset = ((link.lane ?? 0) * 8) % 24
  if (link.route === 'left-gutter' || link.route === 'right-gutter') {
    const sign = link.route === 'left-gutter' ? -1 : 1
    const from = sign < 0 ? a.x : a.x+a.w
    const to = sign < 0 ? b.x : b.x+b.w
    const x = (sign < 0 ? Math.min(from,to) : Math.max(from,to)) + 27*sign
    const y1 = cy(a), y2 = cy(b)
    const bend = Math.min(8,Math.abs(y2-y1)/4)*(Math.sign(y2-y1)||1)
    return { d:`M ${from},${y1} H ${x-8*sign} Q ${x},${y1} ${x},${y1+bend} V ${y2-bend} Q ${x},${y2} ${x-8*sign},${y2} H ${to}`,x,y:y1+(y2-y1)*.27 }
  }
  if (link.route === 'above') {
    const x1 = cx(a), x2 = cx(b), y = Math.min(a.y,b.y)-28
    const bend = Math.min(8,Math.abs(x2-x1)/3)*(Math.sign(x2-x1)||1)
    return {d:`M ${x1},${a.y} V ${y+8} Q ${x1},${y} ${x1+bend},${y} H ${x2-bend} Q ${x2},${y} ${x2},${y+8} V ${b.y}`,x:(x1+x2)/2,y:y-10}
  }
  const sameCol = Math.abs(dx) < 56
  const vertical = sameCol
  const sign = vertical ? Math.sign(dy) || 1 : Math.sign(dx) || 1
  const loop = sameCol && Math.abs(dy) > 110 && a.kind === 'component' && b.kind === 'component' && a.group?.id === b.group?.id && !link.tone
  if (loop) {
    const direction = dy > 0 ? 1 : -1
    const x1 = direction > 0 ? a.x+a.w : a.x
    const x2 = direction > 0 ? b.x+b.w : b.x
    const x = (direction > 0 ? Math.max(x1,x2) : Math.min(x1,x2)) + direction * (25 + offset)
    return { d:`M ${x1},${cy(a)} C ${x},${cy(a)} ${x},${cy(b)} ${x2},${cy(b)}`, x, y:(cy(a)+cy(b))/2 }
  }
  const x1 = vertical ? cx(a)+offset : sign > 0 ? a.x+a.w : a.x
  const x2 = vertical ? cx(b)+offset : sign > 0 ? b.x : b.x+b.w
  const y1 = vertical ? sign > 0 ? a.y+a.h : a.y : cy(a) + (dual ? sign*16 : 0) + offset
  const y2 = vertical ? sign > 0 ? b.y : b.y+b.h : cy(b) + (dual ? sign*16 : 0) + offset
  const x = (x1+x2)/2, y = (y1+y2)/2
  const label = vertical ? { x:x+43,y } : { x,y:y-11 }
  return { d: vertical ? `M ${x1},${y1} C ${x1},${y} ${x2},${y} ${x2},${y2}` : `M ${x1},${y1} C ${x},${y1} ${x},${y2} ${x2},${y2}`, ...label }
}
