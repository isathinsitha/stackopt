import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight, ChevronRight, ExternalLink, Plus, Trash2, X } from 'lucide-react'
import type { Algorithm, Architecture, Component, Connection, Dataset, Group, Parameter, Reference, Variable } from './schema'
import { categories, classes, emptyAlgorithm, emptyDataset, gateResults, researchDecisions, kinds, newParameter, newVariable, statuses } from './schema'

export function Field({ label, value, onChange, area = false, required = false, check, hint }: {
  label: string; value: string; onChange: (value: string) => void; area?: boolean; required?: boolean;
  check?: (value: string) => string; hint?: string;
}) {
  const id = useId()
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState('')
  const attrs = {
    id, value: draft ?? value, 'aria-invalid': Boolean(error), 'aria-describedby': error || hint ? id + '-hint' : undefined,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setDraft(e.target.value)
      setError('')
    },
    onBlur: () => {
      if (draft === null) return
      const message = required && !draft.trim() ? 'This field is required.' : check?.(draft)
      if (message) { setError(message); return }
      if (draft !== value) onChange(draft)
      setDraft(null)
    },
    onKeyDown: (e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      if (!area && e.key === 'Enter') e.currentTarget.blur()
      if (e.key === 'Escape') { setError(''); setDraft(null); e.stopPropagation() }
    },
  }
  return <div className="field"><label htmlFor={id}>{label}</label>
    {area ? <textarea {...attrs} rows={3}/> : <input {...attrs} />}
    {(error || hint) && <small id={id + '-hint'} className={error ? 'error-text' : ''}>{error || hint}</small>}
  </div>
}
export function Select<T extends string>({ label, value, options, onChange }: {
  label: string; value: T; options: readonly (T | { value: T; label: string })[]; onChange: (value: T) => void
}) {
  return <label className="field">{label}<select value={value} onChange={e => onChange(e.target.value as T)}>
    {options.map(option => typeof option === 'string' ? <option key={option} value={option}>{option.replaceAll('_',' ')}</option> :
      <option key={option.value} value={option.value}>{option.label}</option>)}
  </select></label>
}
const groupOptions = (doc: Architecture) => doc.groups.map(group => ({ value: group.id, label: group.name }))
const nodeOptions = (doc: Architecture, skip?: string) => doc.components.filter(item => item.id !== skip).map(item => ({ value:item.id, label:item.name }))
const emptyNode = { value:'', label:'Unspecified' }

function RecordList<T>({ label, records, create, name, change, children }: {
  label: string; records: T[]; create: () => T; name: (record: T) => string;
  change: (records: T[]) => void; children: (record: T, edit: (patch: Partial<T>) => void) => ReactNode;
}) {
  return <section className="record-list">
    <div className="section-head"><h3>{label} <span>{records.length}</span></h3>
      <button className="quiet" onClick={() => change([...records, create()])}><Plus size={13}/> Add</button>
    </div>
    {records.map((record,index) => <details className="record" key={index} open={records.length === 1 || undefined}>
      <summary><ChevronRight size={13}/><span>{name(record)}</span></summary>
      <div className="record-body">
        {children(record, patch => change(records.map((item,i) => i === index ? { ...item,...patch } : item)))}
        <button className="quiet danger" onClick={() => change(records.filter((_,i) => i !== index))}><Trash2 size={13}/> Remove entry</button>
      </div>
    </details>)}
    {records.length === 0 && <p className="muted compact">No entries.</p>}
  </section>
}
function variables(output: boolean, doc: Architecture, records: Variable[], change: (items: Variable[]) => void) {
  return <RecordList label={output ? 'Outputs' : 'Inputs'} records={records} create={newVariable} name={item => item.name + (item.unit ? ' · ' + item.unit : '')} change={change}>
    {(item,edit) => <>
      <Field label="Name" value={item.name} onChange={name => edit({name})} required/>
      <div className="field-grid"><Field label="Data type" value={item.type} onChange={type => edit({type})}/>
        <Field label="Unit" value={item.unit} onChange={unit => edit({unit})}/></div>
      <Field label="Description" area value={item.description} onChange={description => edit({description})}/>
      <Select label={output ? 'Destination component' : 'Source component'} value={item.componentId} options={[emptyNode, ...nodeOptions(doc)]} onChange={componentId => edit({componentId})}/>
      <Select label="Data classification" value={item.classification ?? ''} options={[{value:'',label:'Unspecified'},...classes]} onChange={classification=>edit({classification:classification || undefined})}/>
      {output ? <Field label="Output limitations" value={item.limitations ?? ''} area onChange={limitations=>edit({limitations})}/> : <>
        <Field label="Valid range" value={item.validRange ?? ''} onChange={validRange=>edit({validRange})}/>
        <Field label="Availability" value={item.availability ?? ''} onChange={availability=>edit({availability})}/>
      </>}
      {!output && <><label className="check"><input type="checkbox" checked={item.required} onChange={e => edit({required:e.target.checked})}/>Required input</label>
        <Field label="Default value" value={item.defaultValue} onChange={defaultValue => edit({defaultValue})}/></>}
    </>}
  </RecordList>
}
function params(records: Parameter[], change: (items: Parameter[]) => void) {
  return <RecordList label="Parameters" records={records} create={newParameter} name={item => [item.name,item.defaultValue,item.unit].filter(Boolean).join(' · ')} change={change}>
    {(item,edit) => <>
      <Field label="Name" value={item.name} onChange={name => edit({name})} required/>
      <div className="field-grid"><Field label="Type" value={item.type} onChange={type => edit({type})}/>
        <Field label="Unit" value={item.unit} onChange={unit => edit({unit})}/></div>
      <Field label="Default value" value={item.defaultValue} onChange={defaultValue => edit({defaultValue})}/>
      <Field label="Symbol" value={item.symbol ?? ''} onChange={symbol=>edit({symbol})}/>
      <Field label="Parameter source" value={item.source ?? ''} onChange={source=>edit({source})}/>
      <Field label="Scientific status" value={item.scientificStatus ?? ''} onChange={scientificStatus=>edit({scientificStatus})}/>
      <Select label="Provenance" value={item.provenance} options={['Assumption','Observed input','Derived','Simulated','TBD']} onChange={provenance => edit({provenance})}/>
      <Field label="Description" value={item.description} area onChange={description => edit({description})}/>
      <Field label="Constraints" value={item.constraints} area onChange={constraints => edit({constraints})}/>
    </>}
  </RecordList>
}
const algorithmFields: [keyof Algorithm,string][] = [
  ['name','Algorithm name'],['family','Algorithm family'],['description','General description'],['method','Implementation approach'],
  ['formula','Formula'],['variables','Variables and units'],['assumptions','Assumptions'],['edgeCases','Numerical edge cases'],['pseudocode','Pseudocode'],['alternatives','Alternatives'],['complexity','Complexity'],
  ['limitations','Limitations'],['validation','Validation requirements'],['implementation','Implementation reference'],
]
const datasetFields: [keyof Dataset,string][] = [
  ['mission','Project or study'],['instrument','Instrument'],['product','Product / identifier'],['provider','Provider'],['dataType','Data type'],['format','Native format'],
  ['resolution','Resolution or scale'],['crs','Reference frame or unit system'],['coverage','Coverage'],['temporal','Temporal characteristics'],
  ['processingLevel','Processing level'],['accessMethod','Access method'],['limitations','Scientific limitations'],['availability','Availability'],['verification','Verification'],
]
function ReferenceList({ records, change }: { records: Reference[]; change: (records: Reference[]) => void }) {
  return <>
    <div className="references">{records.map((reference,i) => <div key={i}>{reference.url ? <a href={reference.url} target="_blank" rel="noreferrer">{reference.label}<ExternalLink size={12}/></a> : <span>{reference.label}</span>}
      {reference.locator && <small>{reference.locator}</small>}</div>)}</div>
    <RecordList<Reference> label="Edit references" records={records} name={item => item.label} create={() => ({label:'New reference',url:'',locator:''})} change={change}>
      {(item,edit) => <>
        <Field label="Label" value={item.label} onChange={label => edit({label})} required/>
        <Field label="Source URL" value={item.url} onChange={url => edit({url})} check={text => {
          if (!text) return ''
          try { return ['http:','https:'].includes(new URL(text).protocol) ? '' : 'Enter an HTTP or HTTPS URL.' }
          catch { return 'Enter a complete source URL.' }
        }}/>
        <Field label="Report section or locator" value={item.locator} onChange={locator => edit({locator})}/>
        <Field label="Evidence type" value={item.evidenceType ?? ''} onChange={evidenceType=>edit({evidenceType})}/>
        <Field label="Verification status" value={item.verification ?? ''} onChange={verification=>edit({verification})}/>
        <Field label="Evidence notes" value={item.notes ?? ''} area onChange={notes=>edit({notes})}/>
      </>}
    </RecordList>
  </>
}
function Dependencies({ doc, dependencies, change }: { doc: Architecture; dependencies: string[]; change: (items: string[]) => void }) {
  return <RecordList label="Explicit dependencies" records={dependencies} name={id => doc.components.find(item => item.id === id)?.name ?? id}
    create={() => doc.components.find(item => !dependencies.includes(item.id))?.id ?? dependencies[0]} change={change}>
    {(id,edit) => <Select label="Component" value={id} options={nodeOptions(doc)} onChange={next => change(dependencies.map(key => key === id ? next : key))}/>}
  </RecordList>
}

export function InspectorFrame({ title, eyebrow, close, children, caption }: {
  title: string; eyebrow: string; caption?: string; close: () => void; children: ReactNode
}) {
  return <aside className="inspector" aria-label="Inspector">
    <div className="inspector-head">
      <div className="eyebrow">{eyebrow}</div>
      <button className="icon-button close-inspector" onClick={close} aria-label="Close inspector" title="Close inspector"><X size={17}/></button>
      <h2>{title}</h2>
      {caption && <p>{caption}</p>}
    </div>
    {children}
  </aside>
}
export function ComponentInspector({ doc, item, close, edit, rename, remove, reveal, caption }: {
  doc: Architecture; item: Component; close: () => void; edit: (patch: Partial<Component>) => void; rename: (id: string) => void;
  remove: () => void; reveal: (id: string) => void; caption?: string;
}) {
  const [tab,setTab] = useState('Details')
  const isModel = Boolean(item.algorithm || item.category === 'Scientific model' || item.category === 'Algorithm')
  const isDataset = Boolean(item.dataset || item.category === 'External dataset')
  const relation = (items: Component[], label: string, upstream: boolean) => <section className="relation">
    <h3>{label} <span>{items.length}</span></h3>
    {items.length ? items.map(node => <button className="relation-row" key={node.id} onClick={() => reveal(node.id)}>{upstream ? <ArrowUpRight size={14}/> : <ArrowDownRight size={14}/>} {node.name}</button>) : <p className="muted compact">None.</p>}
  </section>
  const tech = item.technology.join(' · ')
  return <InspectorFrame title={item.name} eyebrow={item.category + ' / ' + item.priority} close={close} caption={caption ?? tech}>
    <div className="inspector-tabs" aria-label="Component specifications">
      {['Details','I/O',...(isModel ? ['Model'] : ['Parameters']),...(isDataset ? ['Dataset'] : []),...(item.gate ? ['Quality gate'] : []),...(item.review || isModel ? ['Review'] : []),'Links'].map(label =>
        <button key={label} aria-pressed={tab === label} onClick={() => setTab(label)}>{label}</button>)}
    </div>
    <div className="inspector-body" key={tab}>
      {tab === 'Details' && <>
        <div className="classification"><span>{item.classification}</span><span>{item.status.replaceAll('_',' ')}</span></div>
        <Field label="Name" value={item.name} onChange={name => edit({name})} required/>
        <Field label="Purpose" value={item.purpose} area onChange={purpose => edit({purpose})}/>
        <Field label="Description" value={item.description} area onChange={description => edit({description})}/>
        <Field label="Technology / function" value={tech} onChange={value => edit({technology:value.split(' · ').filter(Boolean)})} hint="Separate entries with a middle dot."/>
        <div className="field-grid">
          <Select label="Status" options={statuses} value={item.status} onChange={status => edit({status})}/>
          <Select label="Priority" options={['P0','P1','P2','P3']} value={item.priority} onChange={priority => edit({priority})}/>
        </div>
        <Select label="Category" options={categories} value={item.category} onChange={category => edit({category})}/>
        <Select label="Classification" options={classes} value={item.classification} onChange={classification => edit({classification})}/>
        <Select label="Subsystem" options={groupOptions(doc)} value={item.groupId} onChange={groupId => edit({groupId})}/>
        {doc.modelRevision && <Select label="Scientific model family" options={[{value:'',label:'Use subsystem'},...groupOptions(doc)]}
          value={item.modelFamily ?? ''} onChange={modelFamily=>edit({modelFamily:modelFamily || undefined})}/>}
        <Field label="Owner" value={item.owner} onChange={owner => edit({owner})}/>
        <Field label="Module or source path" value={item.module} onChange={module => edit({module})}/>
        <Field label="Known risks" value={item.risks} area onChange={risks => edit({risks})}/>
        <Field label="Notes" value={item.notes} area onChange={notes => edit({notes})}/>
        <Field label="Component ID" value={item.id} onChange={rename} required check={id => {
          if (!/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(id)) return 'Start with a letter. Use letters, numbers, underscores or hyphens.'
          return doc.components.some(node => node.id === id && node.id !== item.id) ? 'This ID is already in use.' : ''
        }}/>
        <button className="quiet danger" onClick={remove}><Trash2 size={14}/> Delete component</button>
      </>}
      {tab === 'I/O' && <>{variables(false,doc,item.inputs,inputs => edit({inputs}))}{variables(true,doc,item.outputs,outputs => edit({outputs}))}</>}
      {(tab === 'Model' || tab === 'Parameters') && <>
        <p className="muted compact">Blueprint specification. Edits are saved in this architecture document.</p>
        {params(item.parameters, parameters => edit({parameters}))}
        {tab === 'Model' && <section className="record-list"><h3>Algorithm specification</h3>
          {algorithmFields.map(([key,label]) => <Field key={key} label={label} value={(item.algorithm ?? emptyAlgorithm)[key] ?? ''} area={key !== 'name' && key !== 'family' && key !== 'implementation'} onChange={value => edit({algorithm:{ ...(item.algorithm ?? emptyAlgorithm),[key]:value }})}/>)}
        </section>}
      </>}
      {tab === 'Dataset' && <>
        <ReferenceList records={item.references} change={references => edit({references})}/>
        {datasetFields.map(([key,label]) => <Field key={key} label={label} value={(item.dataset ?? emptyDataset)[key] ?? ''} area={['coverage','limitations','crs','verification'].includes(key)} onChange={value => edit({dataset:{ ...(item.dataset ?? emptyDataset),[key]:value }})}/>)}
      </>}
      {tab === 'Quality gate' && item.gate && (() => {
        const gate = item.gate
        return <>
          <Select label="Gate result" value={gate.result} options={gateResults} onChange={result=>edit({gate:{...gate,result}})}/>
          <Field label="Gate code" value={gate.code} onChange={code=>edit({gate:{...gate,code}})}/>
          <Field label="Responsible processing stage" value={gate.stage} onChange={stage=>edit({gate:{...gate,stage}})}/>
          <Field label="Acceptance criteria" value={gate.acceptance} area onChange={acceptance=>edit({gate:{...gate,acceptance}})}/>
          <Field label="Failure conditions and handling" value={gate.failure} area onChange={failure=>edit({gate:{...gate,failure}})}/>
          <Field label="Related outputs" value={gate.output} area onChange={output=>edit({gate:{...gate,output}})}/>
        </>
      })()}
      {tab === 'Review' && (() => {
        const review = item.review ?? {decision:'Proposed' as const,foundation:'',availability:'',value:'',difficulty:'',validationStatus:'Not evaluated',uncertainty:''}
        return <>
          <Select label="Research decision" value={review.decision} options={researchDecisions} onChange={decision=>edit({review:{...review,decision}})}/>
          {([['foundation','Scientific foundation'],['availability','Input availability'],['value','Role in system'],['difficulty','Implementation difficulty'],['validationStatus','Validation status'],['uncertainty','Uncertainty and applicability']] as const).map(([key,label])=>
            <Field key={key} label={label} value={review[key]} area onChange={value=>edit({review:{...review,[key]:value}})}/>)}
          <ReferenceList records={item.references} change={references=>edit({references})}/>
        </>
      })()}
      {tab === 'Links' && <>
        {relation(doc.components.filter(node => doc.connections.some(edge => edge.source === node.id && edge.target === item.id)),'Upstream',true)}
        {relation(doc.components.filter(node => doc.connections.some(edge => edge.target === node.id && edge.source === item.id)),'Downstream',false)}
        <Dependencies doc={doc} dependencies={item.dependencies} change={dependencies => edit({dependencies})}/>
        <ReferenceList records={item.references} change={references => edit({references})}/>
      </>}
    </div>
  </InspectorFrame>
}
export function EdgeInspector({ doc, edge, bundle, pick, edit, remove, close }: {
  doc: Architecture; edge: Connection; bundle: Connection[]; pick: (id: string) => void;
  edit: (patch: Partial<Connection>) => void; remove: () => void; close: () => void;
}) {
  return <InspectorFrame title={edge.label} eyebrow="Directed connection" close={close}>
    <div className="inspector-body" key={edge.id}>
      {bundle.length > 1 && <Select label={`Underlying connections (${bundle.length})`} value={edge.id} options={bundle.map(item => ({value:item.id,label:item.label}))} onChange={pick}/>}
      <Field label="Connection label" value={edge.label} onChange={label => edit({label})} required/>
      <Select label="Source" value={edge.source} options={nodeOptions(doc,edge.target)} onChange={source => edit({source})}/>
      <Select label="Destination" value={edge.target} options={nodeOptions(doc,edge.source)} onChange={target => edit({target})}/>
      <Select label="Connection type" value={edge.kind} options={kinds} onChange={kind => edit({kind})}/>
      <Field label="Data transferred" value={edge.payload} onChange={payload => edit({payload})} area/>
      <Field label="Data format" value={edge.format} onChange={format => edit({format})}/>
      <details className="record" open={Boolean(edge.units || edge.spatialReference || edge.resolution || edge.requiredMetadata || edge.failure) || undefined}>
        <summary><ChevronRight size={13}/> Data contract details</summary>
        <div className="record-body">
          {([['units','Units'],['requiredMetadata','Required metadata'],['failure','Failure behavior']] as const).map(([key,label])=>
            <Field key={key} label={label} value={edge[key] ?? ''} area onChange={value=>edit({[key]:value})}/>)}
        </div>
      </details>
      <Field label="Interface or protocol" value={edge.protocol} onChange={protocol => edit({protocol})}/>
      <Field label="Description" value={edge.description} onChange={description => edit({description})} area/>
      <Field label="Validation requirements" value={edge.validation} onChange={validation => edit({validation})} area/>
      <Dependencies doc={doc} dependencies={edge.dependencies} change={dependencies => edit({dependencies})}/>
      <button className="quiet danger" onClick={remove}><Trash2 size={14}/> Disconnect</button>
    </div>
  </InspectorFrame>
}
export function GroupInspector({ doc, group, edit, close, expand, focus, reveal, expanded, modelView }: {
  doc: Architecture; group: Group; edit: (patch: Partial<Group>) => void; close: () => void; expand: () => void;
  focus: () => void; reveal: (id: string) => void; expanded: boolean; modelView?: boolean;
}) {
  const nodes = doc.components.filter(node => ((modelView ? node.modelFamily : undefined) ?? node.groupId) === group.id)
  return <InspectorFrame title={group.name} eyebrow={group.phase + ' / subsystem'} close={close} caption={group.summary}>
    <div className="inspector-body">
      <div className="group-actions"><button className="button" onClick={expand}>{expanded ? 'Collapse' : 'Expand'} on canvas</button><button className="button" onClick={focus}>Focus subsystem</button></div>
      <Field label="Name" value={group.name} onChange={name => edit({name})} required/>
      <Field label="Technology / summary" value={group.summary} onChange={summary => edit({summary})}/>
      <Field label="Description" value={group.description} area onChange={description => edit({description})}/>
      <section className="relation"><h3>Components <span>{nodes.length}</span></h3>
        {nodes.map(node => <button key={node.id} className="relation-row" onClick={() => reveal(node.id)}><ChevronRight size={13}/>{node.name}</button>)}
      </section>
    </div>
  </InspectorFrame>
}
