import { BaseEdge, EdgeLabelRenderer, Handle, Position } from '@xyflow/react'
import type { Edge, EdgeProps, Node, NodeProps } from '@xyflow/react'
import { ArrowDownRight, ArrowUpRight, Boxes, ChevronsUpDown, CircleDot, Database, FlaskConical, Layers3, Route, ScanLine, ShieldCheck, Waypoints } from 'lucide-react'
import type { Box, Link } from './diagram'
import { curve, numberFor } from './diagram'

export type GraphNode = Node<{ box: Box; toggle?: () => void }, 'blueprint' | 'default'>
export type GraphEdge = Edge<{ link: Link; a: Box; b: Box; dual: boolean; inspect: () => void }, 'blueprint'>
const groupIcon = { sources:Database, ingest:Layers3, prep:FlaskConical, pack:Boxes, ui:ScanLine, api:Waypoints, decision:CircleDot, routing:Route, deploy:ArrowDownRight, validate:ShieldCheck }

function BlueprintNode({ data, selected }: NodeProps<GraphNode>) {
  const { box, toggle } = data
  if (box.kind === 'caption') return <div className="canvas-caption">{box.title}</div>
  if (box.kind === 'group') {
    const id = box.group!.id
    const Icon = groupIcon[id as keyof typeof groupIcon] ?? Boxes
    return <div className={`graph-node graph-group tone-${box.tone} ${box.expanded ? 'expanded' : ''} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} className="group-port"/>
      <Handle type="source" position={Position.Right} isConnectable={false} className="group-port"/>
      <div className="group-kicker"><Icon size={12}/><span>{box.subsystemNumber === 'runtime' ? 'RUNTIME CONSUMER' : 'SUBSYSTEM ' + (box.subsystemNumber ?? numberFor(id))}</span></div>
      <div className="graph-title" title={box.title}>{box.title}</div>
      {!box.expanded && <div className="graph-sub" title={box.sub}>{box.sub}</div>}
      <button className="group-toggle nodrag nopan" aria-label={(box.expanded ? 'Collapse ' : 'Expand ') + box.title} title={(box.expanded ? 'Collapse ' : 'Expand ') + box.title}
        onClick={e => { e.stopPropagation(); toggle?.() }}><ChevronsUpDown size={14}/></button>
      {!box.expanded && <span className="group-count" aria-label={`${box.count} components`}>{String(box.count).padStart(2,'0')}</span>}
    </div>
  }
  return <div data-gate-result={box.component?.gate?.result} className={`graph-node graph-component tone-${box.tone} ${selected ? 'selected' : ''} ${box.step ? 'trace-node' : ''} ${box.component?.classification === 'Optional' ? 'optional-node' : ''} ${box.component?.classification === 'Assumption' ? 'assumption-node' : ''}`}>
    <Handle type="target" position={Position.Left} className="connection-handle"/>
    <Handle type="source" position={Position.Right} className="connection-handle"/>
    {box.step && <div className="step-index"><span>{String(box.step).padStart(2,'0')}</span>{box.group?.name}<ArrowUpRight size={12}/></div>}
    <div className="graph-title" title={box.title}>{box.title}</div>
    <div className="graph-sub" title={box.sub}>{box.component?.classification === 'Optional' ? box.component.priority + ' · ' : ''}{box.sub}</div>
  </div>
}

export function ink(kind: Link['kind'], trace: boolean) {
  if (trace) return '#cc957f'
  const colors: Partial<Record<Link['kind'],string>> = { 'Derived product':'#96aab6', Configuration:'#a29379', Provenance:'#817e90', Validation:'#b3907c', Deployment:'#68665f' }
  return colors[kind] ?? '#878a83'
}
export function dashed(kind: Link['kind']) {
  return ['Validation','Deployment','Request','Configuration','Provenance'].includes(kind)
}
function BlueprintEdge({ data, selected, markerEnd }: EdgeProps<GraphEdge>) {
  if (!data) return null
  const { link, a, b, dual } = data
  const { d, x, y } = curve(link,a,b,dual)
  const trace = Boolean(link.tone)
  return <>
    <BaseEdge path={d} markerEnd={markerEnd} style={{ stroke:selected ? '#e0aa92' : ink(link.kind,trace), strokeWidth:selected ? 2 : trace ? 1.5 : 1.15, strokeDasharray:dashed(link.kind) && !trace ? '3 4' : undefined }}/>
    {(link.label && (!link.hideLabel && a.kind === 'group' && b.kind === 'group' || trace || selected)) &&
      <EdgeLabelRenderer>
        <button className={`edge-label nodrag nopan ${trace ? 'trace' : ''} ${selected ? 'selected' : ''}`} title={link.label}
          onClick={e => { e.stopPropagation(); data.inspect() }}
          style={{ transform:`translate(-50%, -50%) translate(${x}px,${y}px)` }}>{link.label}</button>
      </EdgeLabelRenderer>}
  </>
}

export const nodeTypes = { blueprint: BlueprintNode }
export const edgeTypes = { blueprint: BlueprintEdge }
