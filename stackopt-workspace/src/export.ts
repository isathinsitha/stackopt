import type { Box, Link } from './diagram'
import { curve, numberFor } from './diagram'
import { dashed, ink } from './Canvas'

const escape = (text: string) => text.replace(/[<>&"']/g, char => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[char]!))
const colors = { data:'#93a8b5', neutral:'#a7a79a', decision:'#9eae94', constraint:'#c79179' }
function text(x: number, y: number, value: string, size: number, fill: string, mono = false) {
  return `<text x="${x}" y="${y}" font-family="${mono ? 'monospace' : 'Arial,sans-serif'}" font-size="${size}" fill="${fill}">${escape(value)}</text>`
}
function trim(value: string, max: number) {
  return value.length > max ? value.slice(0,max-1) + '…' : value
}
export function diagramSvg(title: string, view: string, version: string, boxes: Box[], links: Link[]) {
  const diagram = boxes.filter(box => box.kind !== 'caption')
  const minX = Math.min(0,...boxes.map(box => box.x)) - 42
  const minY = Math.min(0,...boxes.map(box => box.y)) - 75
  const width = Math.max(480,...boxes.map(box => box.x+box.w)) - minX + 48
  const height = Math.max(175,...boxes.map(box => box.y+(box.regionHeight ?? box.h))) - minY + 65
  const lookup = new Map(boxes.map(box => [box.id,box]))
  const reverse = new Set(links.map(link => link.target + '>' + link.source))
  const lines = links.map(link => {
    const a = lookup.get(link.source)!, b = lookup.get(link.target)!
    const { d,x,y } = curve(link,a,b,reverse.has(link.source + '>' + link.target))
    const show = link.tone || (!link.hideLabel && a.kind === 'group' && b.kind === 'group')
    const stroke = ink(link.kind,Boolean(link.tone))
    const width = link.label.length*6 + 12
    return `<path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.25" ${dashed(link.kind) && !link.tone ? 'stroke-dasharray="3 4"' : ''} marker-end="url(#arrow)"/>` +
      (show ? `<rect x="${x-width/2}" y="${y-8}" width="${width}" height="17" fill="#111211"/>${text(x-width/2+6,y+4,link.label,10,'#a9aaa1',true)}` : '')
  }).join('')
  const regions = diagram.filter(box => box.expanded).map(box => `<rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.regionHeight}" fill="#151615" stroke="#30332f"/>`).join('')
  const nodes = diagram.map(box => {
    const group = box.kind === 'group'
    const topLine = group ? box.subsystemNumber === 'runtime' ? 'RUNTIME CONSUMER' : 'SUBSYSTEM ' + (box.subsystemNumber ?? numberFor(box.group!.id)) : box.step ? String(box.step).padStart(2,'0') + '  ' + box.group?.name : ''
    const titleY = topLine ? box.y+42 : box.y+24
    return `<g><title>${escape(box.title)}</title><rect x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" fill="#191a18" stroke="#3e413b"/>` +
      `<rect x="${box.x}" y="${box.y}" width="2" height="${box.h}" fill="${colors[box.tone]}"/>` +
      (topLine ? text(box.x+14,box.y+18,topLine,9,colors[box.tone],true) : '') +
      text(box.x+14,titleY,trim(box.title,group ? 30 : 27),group ? 15 : 13,'#e7e4db') +
      (!box.expanded ? text(box.x+14,titleY+19,trim(box.sub,group ? 30 : 28),10,'#a2a499',true) : '') + '</g>'
  }).join('')
  const captions = boxes.filter(box => box.kind === 'caption').map(box => text(box.x,box.y+13,box.title,11,'#a19d90',true)).join('')
  return { width, height, svg:`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="${minX} ${minY} ${width} ${height}" role="img" aria-label="${escape(title + ' · ' + view)}"><defs>
  <pattern id="grid" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="0" cy="0" r=".65" fill="#2b2d29"/></pattern>
  <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,1 L7,4 L0,7 Z" fill="#878a83"/></marker>
  </defs><rect x="${minX}" y="${minY}" width="${width}" height="${height}" fill="#111211"/><rect x="${minX}" y="${minY}" width="${width}" height="${height}" fill="url(#grid)"/>
  <text x="${minX+32}" y="${minY+35}" font-size="22" fill="#ebe7db" font-family="Georgia,serif">${escape(title)}</text>
  ${text(minX+33,minY+55,view.toUpperCase()+' · V'+version,10,'#a2a499',true)}
  ${regions}${lines}${nodes}${captions}</svg>` }
}
export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url),1500)
}
export async function rasterize(svg: string, width: number, height: number) {
  const scale = Math.min(2,8192 / Math.max(width,height),Math.sqrt(24_000_000/(width*height)))
  const url = URL.createObjectURL(new Blob([svg],{type:'image/svg+xml;charset=utf-8'}))
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = Math.ceil(width*scale)
    canvas.height = Math.ceil(height*scale)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('PNG rendering is unavailable in this browser.')
    context.drawImage(image,0,0,canvas.width,canvas.height)
    return await new Promise<Blob>((resolve,reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not render the PNG.')), 'image/png'))
  } finally { URL.revokeObjectURL(url) }
}
