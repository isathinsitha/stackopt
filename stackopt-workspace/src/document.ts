import { architectureSchema } from './schema'
import type { Architecture, Connection, Point, LayoutKey } from './schema'
import { initialArchitecture } from './initial'
import upgrade from './blueprint-v011-delta.json'

export const storageKey = 'stackopt-architecture/v1'
export function loadDocument(): { doc: Architecture; error: string } {
  try {
    const value = localStorage.getItem(storageKey)
    return { doc:value ? upgradeDefaultBlueprint(architectureSchema.parse(JSON.parse(value))) : initialArchitecture, error:'' }
  } catch {
    return { doc:initialArchitecture, error:'The saved document could not be opened. The default blueprint is available. Import a backup or reset to resume saving.' }
  }
}

function mergeBlueprintRecords<T extends { id: string }>(
  records: T[], defaults: T[], previousFields: Record<string, object>, addedIds: string[],
): T[] {
  const updatedById = new Map(defaults.map(record => [record.id, record]))
  const existingIds = new Set(records.map(record => record.id))
  const updated = records.map(record => {
    const before = previousFields[record.id]
    const next = updatedById.get(record.id)
    if (!before || !next) return record
    const fields = Object.entries(before).filter(([key, value]) =>
      JSON.stringify(record[key as keyof T]) === JSON.stringify(value))
    return { ...record, ...Object.fromEntries(fields.map(([key]) => [key, next[key as keyof T]])) }
  })
  return updated.concat(addedIds.flatMap(id => {
    const item = updatedById.get(id)
    return item && !existingIds.has(id) ? [item] : []
  }))
}

export function upgradeDefaultBlueprint(doc: Architecture): Architecture {
  if (doc.title !== 'StackOpt' || doc.architectureVersion !== '0.1' ||
      !doc.groups.some(group => group.id === 'allocation') ||
      !doc.decisionSteps.some(step => step.componentId === 'stage-allocation')) return doc

  const components = mergeBlueprintRecords(doc.components, initialArchitecture.components,
    upgrade.components, upgrade.componentsAdded).filter(item => doc.groups.some(group => group.id === item.groupId))
  const ids = new Set(components.map(item => item.id))
  const connections = mergeBlueprintRecords(doc.connections, initialArchitecture.connections,
    upgrade.connections, upgrade.connectionsAdded).filter(edge => ids.has(edge.source) && ids.has(edge.target))
  const edges = new Set(connections.map(edge => edge.id))
  const decisionSteps = doc.decisionSteps.map(step => {
    const component = components.find(item => item.id === step.componentId)
    const next = initialArchitecture.decisionSteps.find(item => item.componentId === step.componentId)
    const before = (upgrade.components as Record<string, { description?: string }>)[step.componentId]?.description
    return {
      ...step,
      caption: next && component && step.caption === before ? next.caption : step.caption,
      connectionIds: step.connectionIds.filter(id => edges.has(id)),
    }
  })
  const missing = initialArchitecture.components.filter(item => !ids.has(item.id)).map(item => item.id)
  return architectureSchema.parse(removeItems({
    ...doc, architectureVersion: initialArchitecture.architectureVersion, components, connections, decisionSteps,
  }, missing, []))
}
export function renameNode(doc: Architecture, oldId: string, id: string): Architecture {
  const replace = (value: string) => value === oldId ? id : value
  return {
    ...doc,
    components:doc.components.map(node => ({
      ...node,id:replace(node.id),dependencies:node.dependencies.map(replace),
      inputs:node.inputs.map(entry => ({ ...entry,componentId:replace(entry.componentId) })),
      outputs:node.outputs.map(entry => ({ ...entry,componentId:replace(entry.componentId) })),
    })),
    connections:doc.connections.map(edge => ({ ...edge,source:replace(edge.source),target:replace(edge.target),dependencies:edge.dependencies.map(replace) })),
    decisionSteps:doc.decisionSteps.map(step => ({ ...step,componentId:replace(step.componentId) })),
    layout:Object.fromEntries(Object.entries(doc.layout).map(([view,positions]) =>
      [view,Object.fromEntries(Object.entries(positions).map(([key,point]) => [replace(key),point]))])),
  }
}
export function removeItems(doc: Architecture, nodes: string[], edges: string[]): Architecture {
  const drop = new Set(nodes), links = new Set(edges)
  const keep = (id: string) => !drop.has(id)
  const connections = doc.connections.filter(edge => !links.has(edge.id) && keep(edge.source) && keep(edge.target))
  const kept = new Set(connections.map(edge => edge.id))
  return {
    ...doc,
    components:doc.components.filter(node => keep(node.id)).map(node => ({
      ...node,dependencies:node.dependencies.filter(keep),
      inputs:node.inputs.map(entry => keep(entry.componentId) ? entry : { ...entry,componentId:'' }),
      outputs:node.outputs.map(entry => keep(entry.componentId) ? entry : { ...entry,componentId:'' }),
    })),
    connections:connections.map(edge => ({ ...edge,dependencies:edge.dependencies.filter(keep) })),
    decisionSteps:doc.decisionSteps.filter(step => keep(step.componentId)).map(step => ({ ...step,connectionIds:step.connectionIds.filter(id => kept.has(id)) })),
    layout:Object.fromEntries(Object.entries(doc.layout).map(([view,positions]) =>
      [view,Object.fromEntries(Object.entries(positions).filter(([id]) => keep(id)))])),
  }
}
export function setPositions(doc: Architecture, view: LayoutKey, positions: Record<string,Point>): Architecture {
  return { ...doc,layout:{ ...doc.layout,[view]:{ ...doc.layout[view],...positions } } }
}
export function newEdge(source: string, target: string, label: string): Connection {
  return { id:'link-' + crypto.randomUUID(), source, target, label, kind:'Data flow', payload:'', format:'', protocol:'', description:'', validation:'', dependencies:[] }
}
