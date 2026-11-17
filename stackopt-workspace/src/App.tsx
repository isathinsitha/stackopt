import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Background, MarkerType, ReactFlow, ReactFlowProvider, SelectionMode, useReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Connection as FlowConnection, NodeChange } from '@xyflow/react'
import { ArrowDownToLine, ArrowLeft, ArrowUpRight, Check, ChevronDown, CircleHelp, Crosshair, Filter, Focus, Link2, Minus, Layers3, Plus, Redo2, Search, Trash2, Undo2, X } from 'lucide-react'
import { edgeTypes, ink, nodeTypes } from './Canvas'
import type { GraphEdge, GraphNode } from './Canvas'
import { buildDiagram, groupKey, switchSettings, viewCopy, viewLabels } from './diagram'
import type { Box, Link } from './diagram'
import { loadDocument, newEdge, removeItems, renameNode, setPositions, storageKey, upgradeDefaultBlueprint } from './document'
import { diagramSvg, download, rasterize } from './export'
import { ComponentInspector, EdgeInspector, Field, GroupInspector, Select } from './Inspector'
import { initialArchitecture } from './initial'
import { layoutKey, lenses } from './pipeline-layout'
import { modelViews } from './model-layout'
import { architectureSchema, categories, newComponent, pipelineLenses, modelLenses, statuses, views } from './schema'
import type { Architecture, Component, ModelLens, PipelineLens, Point, View, ViewSettings } from './schema'

type Modal = 'component' | 'connect' | 'reset' | 'help' | null
type History = { past: Architecture[]; doc: Architecture; future: Architecture[] }
type FitTarget = 'all' | string
const MAX_HISTORY = 45

function IconButton({ label, children, ...props }: React.ComponentProps<'button'> & { label:string; children:ReactNode }) {
  return <button {...props} type="button" className={'icon-button ' + (props.className ?? '')} aria-label={label} title={label}>{children}</button>
}
function Dialog({ title, close, children }: { title:string; close:() => void; children:ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { ref.current?.showModal() },[])
  return <dialog ref={ref} onCancel={close} aria-labelledby="dialog-title">
    <div className="dialog-head"><h2 id="dialog-title">{title}</h2><IconButton label="Close dialog" onClick={close}><X size={16}/></IconButton></div>
    {children}
  </dialog>
}

function Workspace() {
  const [loaded] = useState(loadDocument)
  const [history,setHistory] = useState<History>({ past:[],doc:loaded.doc,future:[] })
  const doc = history.doc
  const [settings,setSettings] = useState<ViewSettings>(loaded.doc.viewSettings)
  const lens = settings.pipelineLens ?? 'complete'
  const isPipeline = Boolean(settings.view === 'pipeline' && doc.pipelineRevision)
  const modelLens = settings.modelLens ?? 'complete'
  const isModels = Boolean(settings.view === 'models' && doc.modelRevision)
  const currentLayout = layoutKey(settings,doc.pipelineRevision,doc.modelRevision)
  const [blockedSave,setBlockedSave] = useState(Boolean(loaded.error))
  const [saveStatus,setSaveStatus] = useState('Saved locally')
  const [notice,setNotice] = useState(loaded.error)
  const [selected,setSelected] = useState<string[]>([])
  const [edgeIds,setEdgeIds] = useState<string[]>([])
  const [selectedEdge,setSelectedEdge] = useState('')
  const [graphEdge,setGraphEdge] = useState('')
  const [dragging,setDragging] = useState<Record<string,Point>>({})
  const [measured,setMeasured] = useState<Record<string, { width:number; height:number }>>({})
  const [zoom,setZoom] = useState(1)
  const [search,setSearch] = useState('')
  const [searchOpen,setSearchOpen] = useState(false)
  const [menu,setMenu] = useState<'file' | 'filter' | ''>('')
  const [modal,setModal] = useState<Modal>(null)
  const [fitTarget,setFitTarget] = useState<FitTarget | null>(loaded.doc.viewSettings.viewport ? null : 'all')
  const [ready,setReady] = useState(false)
  const [newName,setNewName] = useState('')
  const [newCategory,setNewCategory] = useState<Component['category']>('Scientific model')
  const [newGroup,setNewGroup] = useState('runtime')
  const [edgeSource,setEdgeSource] = useState('')
  const [edgeTarget,setEdgeTarget] = useState('')
  const [formError,setFormError] = useState('')
  const stage = useRef<HTMLDivElement>(null)
  const searchInput = useRef<HTMLInputElement>(null)
  const importer = useRef<HTMLInputElement>(null)
  const flow = useReactFlow<GraphNode,GraphEdge>()

  const edit = useCallback((update: (doc:Architecture) => Architecture) => {
    setHistory(state => ({ past:[...state.past.slice(-MAX_HISTORY+1),state.doc],doc:update(state.doc),future:[] }))
  },[])
  function undo() {
    setHistory(state => state.past.length ? {
      past:state.past.slice(0,-1), doc:state.past[state.past.length-1], future:[state.doc,...state.future],
    } : state)
  }
  function redo() {
    setHistory(state => state.future.length ? { past:[...state.past,state.doc],doc:state.future[0],future:state.future.slice(1) } : state)
  }
  useEffect(() => {
    if (blockedSave) return
    try {
      localStorage.setItem(storageKey,JSON.stringify({ ...doc,viewSettings:settings }))
      setSaveStatus('Saved locally')
    } catch {
      setSaveStatus('Save unavailable')
      setNotice('Browser storage is unavailable or full. Export JSON to keep your work.')
    }
  },[doc,settings,blockedSave])
  useEffect(() => {
    if (!notice || blockedSave) return
    const timer = window.setTimeout(() => setNotice(''),6500)
    return () => window.clearTimeout(timer)
  },[notice,blockedSave])

  const diagram = useMemo(() => buildDiagram(doc,settings),[doc,settings])
  const displayed = useMemo(() => diagram.boxes.map(box => {
    const moved = dragging[box.id]
    if (moved) return { ...box,...moved }
    const groupMoved = box.groupOrigin && dragging[groupKey(box.group!.id)]
    if (groupMoved && box.groupOrigin) return { ...box,x:box.x + groupMoved.x - box.groupOrigin.x,y:box.y + groupMoved.y - box.groupOrigin.y }
    return box
  }),[diagram.boxes,dragging])
  const byId = useMemo(() => new Map(displayed.map(box => [box.id,box])),[displayed])
  const activeId = selected.length === 1 ? selected[0] : ''
  const item = doc.components.find(node => node.id === activeId)
  const group = doc.groups.find(group => groupKey(group.id) === activeId)
  const edge = doc.connections.find(link => link.id === selectedEdge)
  const bundle = doc.connections.filter(link => edgeIds.includes(link.id))
  const showInspector = Boolean(item || group || edge || selected.length > 1)
  const previewCaption = settings.view === 'decision' && !settings.focus ? doc.decisionSteps.find(step => step.componentId === item?.id)?.caption : undefined

  const fit = useCallback((target: FitTarget = 'all', animate = true) => {
    const element = stage.current
    if (!element) return
    const canvas = displayed.filter(box => box.kind !== 'caption')
    const one = target === 'all' ? null : byId.get(target)
    const boxes = one ? [one] : canvas
    if (!boxes.length) return
    const x = Math.min(...boxes.map(box => box.x)), y = Math.min(...boxes.map(box => box.y))
    const w = Math.max(...boxes.map(box => box.x + box.w)) - x
    const h = Math.max(...boxes.map(box => box.y + (box.regionHeight ?? box.h))) - y
    const width = element.clientWidth, height = element.clientHeight
    const marginX = width < 600 ? 18 : 46
    const marginY = height < 480 ? 20 : 46
    const nextZoom = Math.max(.12,Math.min(one ? 1.16 : 1.08,(width - marginX*2)/w,(height - marginY*2)/h))
    setZoom(nextZoom)
    const viewport = { x:(width - w*nextZoom)/2 - x*nextZoom, y:(height - h*nextZoom)/2 - y*nextZoom, zoom:nextZoom }
    void flow.setViewport(viewport,{duration:animate ? 180 : 0})
    setSettings(prev => ({ ...prev,viewport }))
  },[byId,displayed,flow])
  useEffect(() => {
    if (!fitTarget || !ready) return
    const frame = requestAnimationFrame(() => { fit(fitTarget,false); setFitTarget(null) })
    return () => cancelAnimationFrame(frame)
  },[fitTarget,fit,ready])
  const clear = useCallback(() => { setSelected([]); setSelectedEdge(''); setEdgeIds([]); setGraphEdge('') },[])
  function inspect(link: Link) {
    setSelected([])
    setSelectedEdge(link.links[0].id)
    setEdgeIds(link.links.map(edge => edge.id))
    setGraphEdge(link.id)
  }
  function setView(view: View) {
    setSettings(current => ({ ...switchSettings(current,view,doc.pipelineRevision,doc.modelRevision),category:'',status:'' }))
    clear(); setMenu(''); setFitTarget('all')
  }
  function setLens(pipelineLens: PipelineLens) {
    setSettings(current=>({ ...current,pipelineLens,expanded:lenses[pipelineLens].open,focus:'',category:'',status:'',viewport:undefined }))
    clear(); setFitTarget('all')
  }
  function setModelLens(modelLens: ModelLens) {
    setSettings(current=>({...current,modelLens,expanded:modelViews[modelLens].open,focus:'',category:'',status:'',viewport:undefined}))
    clear(); setFitTarget('all')
  }
  function toggleGroup(id: string) {
    setSettings(current => current.focus ? { ...current,focus:'',expanded:[],viewport:undefined } : {
      ...current, expanded:current.expanded.includes(id) ? current.expanded.filter(value => value !== id) : [...current.expanded,id],
    })
    setFitTarget((isPipeline || isModels) && !settings.focus && !settings.expanded.includes(id) ? groupKey(id) : 'all')
  }
  function focusGroup(id: string) {
    setSettings(current => ({ ...current,focus:id,category:'',status:'',viewport:undefined }))
    setFitTarget('all')
  }
  function reveal(id: string) {
    const node = doc.components.find(node => node.id === id)
    if (!node) return
    if (!byId.has(id)) setSettings(current => ({ ...current,focus:(isModels ? node.modelFamily : undefined) ?? node.groupId,category:'',status:'',viewport:undefined }))
    setSelected([id]); setSelectedEdge(''); setEdgeIds([]); setGraphEdge(''); setSearchOpen(false); setSearch('')
    setFitTarget(id)
  }
  useEffect(() => {
    const query = new URLSearchParams(location.search)
    const component = doc.components.find(item => item.id === query.get('component'))
    if (component) {
      const view = component.modelFamily || component.review ? 'models' : component.groupId === 'runtime' || component.groupId === 'cad' ? 'runtime' : 'pipeline'
      setSettings(current => ({
        ...switchSettings(current,view,doc.pipelineRevision,doc.modelRevision),
        focus:component.modelFamily ?? component.groupId,category:'',status:'',viewport:undefined,
      }))
      setSelected([component.id])
      setFitTarget(component.id)
    } else if (query.get('view') === 'models') setView('models')
    // A deep link sets the starting view. Later canvas edits own selection.
  },[])
  function removeSelection() {
    const nodes = selected.filter(id => doc.components.some(node => node.id === id))
    if (!nodes.length && !edge) return
    edit(current => removeItems(current,nodes,edge ? [edge.id] : []))
    setNotice(nodes.length ? `Removed ${nodes.length} component${nodes.length === 1 ? '' : 's'}.` : 'Disconnected.')
    clear()
  }
  useEffect(() => {
    function keydown(e: KeyboardEvent) {
      if (modal || e.defaultPrevented) return
      const el = e.target as HTMLElement
      const writing = el.closest('input,textarea,select,[contenteditable]')
      if (e.key === 'Escape') { setMenu(''); setSearchOpen(false); clear(); return }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); setSearchOpen(true); searchInput.current?.focus(); return
      }
      if (writing) return
      if ((e.metaKey || e.ctrlKey) && ['z','y'].includes(e.key.toLowerCase())) {
        e.preventDefault()
        if (e.shiftKey || e.key.toLowerCase() === 'y') redo()
        else undo()
      } else if (e.key.toLowerCase() === 'f' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault(); fit()
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selected.length || edge) { e.preventDefault(); removeSelection() }
      }
    }
    window.addEventListener('keydown',keydown)
    return () => window.removeEventListener('keydown',keydown)
  })
  function changeNodes(changes: NodeChange<GraphNode>[]) {
    const dimensions = changes.filter(change => change.type === 'dimensions').filter(change => change.dimensions)
    if (dimensions.length) setMeasured(prev => {
      const changed = dimensions.filter(change => prev[change.id]?.width !== change.dimensions!.width || prev[change.id]?.height !== change.dimensions!.height)
      return changed.length ? { ...prev,...Object.fromEntries(changed.map(change => [change.id,change.dimensions!])) } : prev
    })
    const selections = changes.filter(change => change.type === 'select')
    if (selections.length) setSelected(prev => {
      const next = new Set(prev)
      selections.forEach(change => change.selected ? next.add(change.id) : next.delete(change.id))
      return [...next]
    })
    const moves = changes.filter(change => change.type === 'position').filter(change => change.position)
    if (moves.some(move => move.dragging)) setDragging(prev => ({
      ...prev,...Object.fromEntries(moves.map(move => [move.id,move.position!])),
    }))
  }
  function finishDrag(nodes: GraphNode[]) {
    const nodeMap = new Map(nodes.map(node => [node.id,node.position]))
    const local = Object.fromEntries(nodes.flatMap(node => {
      const box = node.data.box
      const origin = box.groupOrigin ? nodeMap.get(groupKey(box.group!.id)) ?? box.groupOrigin : {x:0,y:0}
      return [[node.id,{ x:Math.round(node.position.x-origin.x),y:Math.round(node.position.y-origin.y) }]]
    }))
    edit(current => setPositions(current,currentLayout,local))
    setDragging({})
  }
  function selectNode(event: React.MouseEvent, node: GraphNode) {
    setSelectedEdge(''); setEdgeIds([]); setGraphEdge('')
    if (!event.shiftKey && !event.metaKey && !event.ctrlKey) setSelected([node.id])
  }
  function openModal(value: Modal) {
    setMenu(''); setFormError('')
    if (value === 'component') {
      setNewName(''); setNewGroup(group?.id ?? item?.groupId ?? (settings.focus || 'runtime'))
      if (!doc.groups.some(group => group.id === (settings.focus || 'runtime')) && !item && !group) setNewGroup(doc.groups[0].id)
    } else if (value === 'connect') {
      setEdgeSource(item?.id ?? ''); setEdgeTarget('')
    }
    setModal(value)
  }
  function addComponent(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!newName.trim() || !newGroup) { setFormError('Enter a name and choose a subsystem.'); return }
    const node = newComponent('component-'+crypto.randomUUID(),newGroup,newCategory,newName.trim())
    edit(current => ({ ...current,components:[...current.components,node] }))
    setSettings(current => ({ ...current,focus:newGroup,category:'',status:'',viewport:undefined }))
    clear(); setSelected([node.id]); setFitTarget(node.id); setModal(null)
  }
  function connect(source: string, target: string, label = 'New connection') {
    if (!source || !target || source === target || !label.trim()) {
      setFormError('Choose two different components and enter a label.')
      return
    }
    const created = newEdge(source,target,label.trim())
    edit(current => ({ ...current,connections:[...current.connections,created] }))
    setModal(null)
    setSelected([]); setSelectedEdge(created.id); setEdgeIds([created.id]); setGraphEdge(created.id)
  }
  function handleConnect(params: FlowConnection) { connect(params.source,params.target) }
  async function importFile(file: File) {
    try {
      if (file.size > 15_000_000) throw new Error('Use an architecture JSON file under 15 MB.')
      const result = architectureSchema.safeParse(JSON.parse(await file.text()))
      if (!result.success) throw new Error(result.error.issues[0].message)
      const imported = upgradeDefaultBlueprint(result.data)
      edit(() => imported); clear()
      setSettings(imported.viewSettings)
      setBlockedSave(false)
      if (imported.viewSettings.viewport) void flow.setViewport(imported.viewSettings.viewport)
      else setFitTarget('all')
      setNotice('Architecture imported.')
    } catch (error) { setNotice('Import failed. ' + (error instanceof Error ? error.message : 'Invalid architecture file.')) }
  }
  async function exportFile(format: 'json' | 'svg' | 'png') {
    setMenu('')
    const name = 'stackopt-' + (format === 'json' ? 'architecture' : currentLayout)
    try {
      if (format === 'json') {
        const snapshot = architectureSchema.parse({ ...doc,viewSettings:{ ...settings,viewport:flow.getViewport() } })
        download(new Blob([JSON.stringify(snapshot,null,2)+'\n'],{type:'application/json'}),name+'.json')
      } else {
        const image = diagramSvg(doc.title,viewLabel,doc.architectureVersion,displayed,diagram.links)
        const blob = format === 'svg' ? new Blob([image.svg],{type:'image/svg+xml;charset=utf-8'}) : await rasterize(image.svg,image.width,image.height)
        download(blob,name+'.'+format)
      }
      setNotice(format.toUpperCase() + ' exported.')
    } catch (error) { setNotice('Export failed. ' + (error instanceof Error ? error.message : 'Please try again.')) }
  }
  function resetLayout() {
    edit(current => ({ ...current,layout:Object.fromEntries(Object.entries(current.layout).filter(([view]) => view !== currentLayout)) }))
    setMenu(''); setFitTarget('all'); setNotice('Layout reset for this view.')
  }
  function resetDocument() {
    edit(() => initialArchitecture)
    setSettings(initialArchitecture.viewSettings); setBlockedSave(false); setModal(null)
    clear(); setFitTarget('all'); setNotice('Default architecture restored.')
  }

  const reverse = new Set(diagram.links.map(link => link.target+'>'+link.source))
  const nodes: GraphNode[] = displayed.flatMap(box => {
    const node: GraphNode = {
      id:box.id, type:'blueprint', data:{ box,toggle:box.group && box.kind === 'group' ? () => toggleGroup(box.group!.id) : undefined },
      position:{x:box.x,y:box.y}, style:{ width:box.w,height:box.h }, width:box.w,height:box.h, measured:measured[box.id], selected:selected.includes(box.id),
      draggable:box.kind !== 'caption', selectable:box.kind !== 'caption', focusable:box.kind !== 'caption', connectable:box.kind === 'component',
      ariaLabel:box.kind === 'caption' ? box.title : box.kind === 'group' ? box.title + ' subsystem' : box.title,
      zIndex:box.kind === 'caption' ? 0 : 2,
    }
    if (!box.expanded) return [node]
    return [{
      id:'region:' + box.id,type:'default',data:{box,label:''},position:node.position,
      style:{width:box.w,height:box.regionHeight},measured:measured['region:' + box.id],className:'group-region',selectable:false,draggable:false,focusable:false,connectable:false,zIndex:-1,
    },node]
  })
  const edges: GraphEdge[] = diagram.links.map(link => ({
    id:link.id,source:link.source,target:link.target,type:'blueprint',selected:graphEdge === link.id,
    data:{ link,a:byId.get(link.source)!,b:byId.get(link.target)!,dual:reverse.has(link.source+'>'+link.target),inspect:() => inspect(link) },
    markerEnd:{type:MarkerType.ArrowClosed,width:12,height:12,color:ink(link.kind,Boolean(link.tone))},
    ariaLabel:link.label,zIndex:1,
  }))

  const searchTerm = search.trim().toLowerCase()
  const matches = searchTerm ? doc.components.filter(node => [node.name,node.id,node.description,node.category,...node.technology].some(value => value.toLowerCase().includes(searchTerm))).slice(0,14) : []
  const groupChoices = doc.groups.map(group => ({ value:group.id,label:group.name }))
  const componentChoices = [{value:'',label:'Choose a component'}, ...doc.components.map(node => ({value:node.id,label:node.name}))]
  const filterCount = Number(Boolean(settings.category)) + Number(Boolean(settings.status))
  const viewLabel = settings.focus ? doc.groups.find(group => group.id === settings.focus)?.name ?? viewLabels[settings.view] : isPipeline && lens !== 'complete' ? lenses[lens].label : isModels && modelLens !== 'complete' ? modelViews[modelLens].label : viewLabels[settings.view]
  return <div className="app">
    <header className="masthead">
      <div className="brand">
        <div className="brand-icon"><Layers3 size={24} strokeWidth={1.3}/></div>
        <div><h1>{doc.title}</h1><p>SYSTEM ARCHITECTURE <span>·</span> DETERMINISTIC TOLERANCE ANALYSIS</p></div>
      </div>
      <div className="mast-actions">
        <div className="history">
          <IconButton label="Undo" disabled={!history.past.length} onClick={undo}><Undo2 size={16}/></IconButton>
          <IconButton label="Redo" disabled={!history.future.length} onClick={redo}><Redo2 size={16}/></IconButton>
        </div>
        <button className="button add-button" onClick={() => openModal('component')}><Plus size={15}/><span>Add component</span></button>
        <button className="button connect-button" onClick={() => openModal('connect')}><Link2 size={15}/><span>Connect</span></button>
        <div className="popup-anchor">
          <button className="button" aria-expanded={menu === 'file'} onClick={() => setMenu(menu === 'file' ? '' : 'file')}><ArrowDownToLine size={15}/><span>Export</span><ChevronDown size={12}/></button>
          {menu === 'file' && <div className="popup file-menu">
            <button onClick={() => void exportFile('json')}>Export editable JSON</button>
            <button onClick={() => void exportFile('svg')}>Export diagram SVG</button>
            <button onClick={() => void exportFile('png')}>Export diagram PNG</button>
            <hr/>
            <button onClick={() => { setMenu(''); importer.current?.click() }}>Import architecture JSON</button>
            <button onClick={resetLayout}>Reset layout</button>
            <button className="danger" onClick={() => openModal('reset')}>Restore default architecture</button>
          </div>}
          <input ref={importer} type="file" accept=".json,application/json" hidden onChange={e => {
            const file = e.currentTarget.files?.[0]
            if (file) void importFile(file)
            e.currentTarget.value = ''
          }}/>
        </div>
      </div>
    </header>
    <div className="workspace-bar">
      <nav className="views" aria-label="Architecture views">
        {views.map((view,i) => <button key={view} aria-current={settings.view === view ? 'page' : undefined} onClick={() => setView(view)}>
          <span className="view-index">{String(i+1).padStart(2,'0')}</span>{viewLabels[view]}{view === 'decision' && <ArrowUpRight size={12}/>}
        </button>)}
      </nav>
      <div className="workspace-actions">
        <div className="search-wrap popup-anchor" onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setSearchOpen(false) }}>
          <Search size={15}/>
          <input ref={searchInput} aria-label="Find component" placeholder="Find component…" value={search}
            onFocus={() => setSearchOpen(true)} onChange={e => { setSearch(e.target.value); setSearchOpen(true) }}
            onKeyDown={e => { if (e.key === 'Enter' && matches[0]) { e.preventDefault(); reveal(matches[0].id) } }}/>
          <kbd>Ctrl K</kbd>
          {searchOpen && searchTerm && <div className="popup search-results">
            {matches.length ? matches.map(node => <button key={node.id} onClick={() => reveal(node.id)}><span>{node.name}</span><small>{doc.groups.find(group => group.id === node.groupId)?.name}</small></button>) :
              <div className="search-empty">No matching components.</div>}
          </div>}
        </div>
        <div className="popup-anchor">
          <button className={`button filter-button ${filterCount ? 'active' : ''}`} aria-expanded={menu === 'filter'} onClick={() => setMenu(menu === 'filter' ? '' : 'filter')}><Filter size={14}/> Filter {filterCount ? filterCount : ''}</button>
          {menu === 'filter' && <div className="popup filter-menu">
            <Select label="Component type" value={settings.category} options={[{value:'',label:'All types'},...categories]} onChange={category => { setSettings(current => ({...current,category})); clear(); setFitTarget('all') }}/>
            <Select label="Implementation status" value={settings.status} options={[{value:'',label:'All statuses'},...statuses]} onChange={status => { setSettings(current => ({...current,status})); clear(); setFitTarget('all') }}/>
            <button onClick={() => { setSettings(current => ({...current,category:'',status:''})); setMenu(''); setFitTarget('all') }}>Clear filters</button>
          </div>}
        </div>
      </div>
    </div>

    <main className="workspace">
      <section className={`canvas-shell ${isPipeline || isModels ? 'pipeline-shell' : ''}`} aria-label="Architecture canvas">
        <div className="canvas-heading">
          <div>
            <div className="eyebrow">{settings.focus ? <button className="quiet back" onClick={() => { setSettings(current => ({ ...current,focus:'' })); clear(); setFitTarget('all') }}><ArrowLeft size={12}/> {viewLabels[settings.view]}</button> : isPipeline ? 'STACKOPT / DATA CONTRACTS' : isModels ? 'STACKOPT / ENGINEERING MODELS' : settings.view === 'decision' ? 'STACKOPT / IMPLEMENTATION' : 'STACKOPT / SYSTEM DESIGN'}</div>
            <h2>{viewLabel}</h2>
            <p>{settings.focus ? doc.groups.find(group => group.id === settings.focus)?.summary : isPipeline ? lenses[lens].description : isModels ? modelViews[modelLens].description : viewCopy[settings.view]}</p>
          </div>
          <div className="overview-actions">
            {(settings.view === 'system' || settings.view === 'runtime') && !settings.focus && <button className="button" aria-pressed={Boolean(settings.overviewAllLinks)} onClick={()=>setSettings(current=>({...current,overviewAllLinks:!current.overviewAllLinks}))}>All links</button>}
            <div className="view-tag"><span/> PROPOSED BLUEPRINT</div>
          </div>
        </div>
        {isPipeline && <nav className="pipeline-lenses" aria-label="Contract views">
          {pipelineLenses.map(key=><button key={key} aria-current={key === lens ? 'page' : undefined} onClick={()=>setLens(key)}>{lenses[key].label}</button>)}
          <button className="all-pipeline-links" aria-pressed={Boolean(settings.pipelineAllLinks)} onClick={()=>setSettings(current=>({...current,pipelineAllLinks:!current.pipelineAllLinks}))}>All links</button>
        </nav>}
        {isModels && <nav className="pipeline-lenses" aria-label="Engineering model views">
          {modelLenses.map(key=><button key={key} aria-current={key === modelLens ? 'page' : undefined} onClick={()=>setModelLens(key)}>{modelViews[key].label}</button>)}
          <button className="all-pipeline-links" aria-pressed={Boolean(settings.modelAllLinks)} onClick={()=>setSettings(current=>({...current,modelAllLinks:!current.modelAllLinks}))}>All links</button>
        </nav>}
        <div className="stage" ref={stage} onPointerDown={() => { if (menu) setMenu('') }}>
          <ReactFlow<GraphNode,GraphEdge>
            nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} colorMode="dark"
            onInit={() => setReady(true)} onNodesChange={changeNodes}
            onNodeDragStop={(_,node,nodes) => finishDrag(nodes.length ? nodes : [node])}
            onNodeClick={selectNode} onNodeDoubleClick={(_,node) => { if (node.data.box.kind === 'group') toggleGroup(node.data.box.group!.id) }}
            onEdgeClick={(_,edge) => { if (edge.data) inspect(edge.data.link) }}
            onPaneClick={clear} onConnect={handleConnect} isValidConnection={connection => connection.source !== connection.target}
            onMove={(_,viewport) => setZoom(viewport.zoom)}
            onMoveEnd={(event,viewport) => { if (event) setSettings(current => ({ ...current,viewport })) }}
            defaultViewport={loaded.doc.viewSettings.viewport} minZoom={.12} maxZoom={2} deleteKeyCode={null}
            panOnDrag={[0,1,2]} selectionKeyCode="Shift" multiSelectionKeyCode={['Shift','Meta','Control']} selectionMode={SelectionMode.Partial}
            zoomOnDoubleClick={false} onlyRenderVisibleElements={false}
            proOptions={{hideAttribution:true}} aria-label={viewLabel + ' architecture graph'}
          ><Background color="#3c3c34" gap={20} size={.8}/></ReactFlow>
          {!displayed.some(box => box.kind !== 'caption') && <div className="empty-canvas">No components match this view.</div>}
          <div className="zoom-controls" aria-label="Canvas controls">
            <IconButton label="Zoom out" onClick={() => { void flow.zoomOut({duration:130}).then(() => setSettings(current => ({...current,viewport:flow.getViewport()}))) }}><Minus size={15}/></IconButton>
            <span>{Math.round(zoom*100)}%</span>
            <IconButton label="Zoom in" onClick={() => { void flow.zoomIn({duration:130}).then(() => setSettings(current => ({...current,viewport:flow.getViewport()}))) }}><Plus size={15}/></IconButton>
            <IconButton label="Fit to view" onClick={() => fit()}><Focus size={16}/></IconButton>
          </div>
          {settings.view === 'decision' && !settings.focus && <div className="scenario-label"><span/> IMPLEMENTATION ORDER</div>}
          {notice && <div className="toast" role="status">{notice}<IconButton label="Dismiss notice" onClick={() => setNotice('')}><X size={13}/></IconButton></div>}
        </div>
        <div className="canvas-footer">
          <div className="legend" aria-label="Diagram legend">
            <span><i className="swatch data"/> Data & analysis</span><span><i className="swatch decision"/> Decisions</span><span><i className="swatch assumption"/> Assumptions</span><span><i className="swatch constraint"/> Constraints</span>{isPipeline || isModels ? <><span><i className="swatch derived-line"/> Derived product</span><span><i className="swatch config-line"/> Configuration / provenance</span><span><i className="swatch validation-line"/> Validation</span></> : <span><i className="swatch dashed"/> Request / assurance</span>}
          </div>
          <button className="quiet help" onClick={() => openModal('help')}><CircleHelp size={14}/> Canvas guide</button>
        </div>
      </section>
      {showInspector && (item ?
        <ComponentInspector key={item.id} doc={doc} item={item} close={clear} caption={previewCaption} reveal={reveal}
          edit={patch => edit(current => ({ ...current,components:current.components.map(node => node.id === item.id ? { ...node,...patch } : node) }))}
          rename={id => { edit(current => renameNode(current,item.id,id)); setSelected([id]) }} remove={removeSelection}/> :
        group ? <GroupInspector key={group.id} doc={doc} group={group} modelView={isModels} close={clear} reveal={reveal}
          expanded={Boolean(byId.get(groupKey(group.id))?.expanded)} expand={() => toggleGroup(group.id)} focus={() => focusGroup(group.id)}
          edit={patch => edit(current => ({ ...current,groups:current.groups.map(entry => entry.id === group.id ? { ...entry,...patch } : entry) }))}/> :
        edge ? <EdgeInspector doc={doc} edge={edge} bundle={bundle} pick={setSelectedEdge} close={clear} remove={removeSelection}
          edit={patch => edit(current => ({ ...current,connections:current.connections.map(link => link.id === edge.id ? { ...link,...patch } : link) }))}/> :
        <aside className="inspector multi-inspector" aria-label="Selection"><div className="inspector-head"><div className="eyebrow">MULTI-SELECTION</div><h2>{selected.length} selected</h2><IconButton className="close-inspector" label="Clear selection" onClick={clear}><X size={16}/></IconButton></div>
          <div className="inspector-body"><p>Drag to move the selection. Subsystems move with their components.</p>
            <button className="button danger" onClick={removeSelection} disabled={!selected.some(id => doc.components.some(node => node.id === id))}><Trash2 size={14}/> Delete selected components</button></div></aside>)}
    </main>
    <footer className="status-bar">
      <div><span className={`save ${saveStatus === 'Saved locally' && !blockedSave ? '' : 'unsaved'}`}><Check size={12}/> {blockedSave ? 'Autosave paused' : saveStatus}</span><span className="status-divider"/>v{doc.architectureVersion}</div>
      <div className="status-center"><Crosshair size={13}/> LOCAL WORKSPACE</div>
      <div><span>{doc.components.length} components</span><span className="status-divider"/><span>{doc.connections.length} connections</span></div>
    </footer>
    {modal === 'component' && <Dialog title="Add component" close={() => setModal(null)}><form onSubmit={addComponent}>
      <label className="field">Component name<input autoFocus value={newName} onChange={e => setNewName(e.target.value)} required/></label>
      <Select label="Component type" options={categories} value={newCategory} onChange={setNewCategory}/>
      <Select label="Subsystem" options={groupChoices} value={newGroup} onChange={setNewGroup}/>
      {formError && <p className="error-text" role="alert">{formError}</p>}
      <div className="dialog-actions"><button className="button" type="button" onClick={() => setModal(null)}>Cancel</button><button className="button add-button" type="submit">Add component</button></div>
    </form></Dialog>}
    {modal === 'connect' && <Dialog title="Connect components" close={() => setModal(null)}><form onSubmit={e => { e.preventDefault(); connect(edgeSource,edgeTarget,String(new FormData(e.currentTarget).get('label') ?? '')) }}>
      <Select label="Source component" options={componentChoices} value={edgeSource} onChange={setEdgeSource}/>
      <Select label="Destination component" options={componentChoices} value={edgeTarget} onChange={setEdgeTarget}/>
      <label className="field">Connection label<input name="label" placeholder="Data or control passed" required/></label>
      {formError && <p className="error-text" role="alert">{formError}</p>}
      <div className="dialog-actions"><button className="button" type="button" onClick={() => setModal(null)}>Cancel</button><button className="button add-button" type="submit">Connect</button></div>
    </form></Dialog>}
    {modal === 'reset' && <Dialog title="Restore the default architecture?" close={() => setModal(null)}>
      <p>This replaces edits and layouts in the open document. You can undo the change during this session.</p>
      <div className="dialog-actions"><button className="button" onClick={() => setModal(null)}>Cancel</button><button className="button danger" onClick={resetDocument}>Restore default</button></div>
    </Dialog>}
    {modal === 'help' && <Dialog title="Canvas guide" close={() => setModal(null)}>
      <div className="guide"><p>Select a subsystem or component to inspect it. Use the chevrons to expand groups and select an arrow to inspect the underlying contracts.</p>
        <p>Drag the canvas to pan. Scroll to zoom. Shift-drag to box select, or use Shift / Ctrl / ⌘ with clicks. Drag components to rearrange them. Connect using the toolbar or by dragging from a component’s right port to another component’s left port.</p>
        <p><kbd>F</kbd> Fit <kbd>Esc</kbd> Clear <kbd>⌘/Ctrl K</kbd> Find <kbd>Delete</kbd> Remove <kbd>⌘/Ctrl Z</kbd> Undo</p>
        <Field label="Architecture version" value={doc.architectureVersion} required onChange={architectureVersion => edit(current => ({ ...current,architectureVersion }))}/>
      </div>
    </Dialog>}
  </div>
}

export default function App() {
  return <ReactFlowProvider><Workspace/></ReactFlowProvider>
}
