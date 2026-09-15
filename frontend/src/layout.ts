import dagre from '@dagrejs/dagre'
import type { GraphEdge } from './types'

export const BOX_W = 260
export const BOX_H = 112

/**
 * What's on screen: pinned roots, plus everything an expanded, visible box points at — repeated until
 * nothing new appears. Collapsing a box removes what only it revealed; shared targets stay.
 */
export function visibleIds(pinned: Set<string>, expanded: Set<string>, out: Map<string, string[]>): Set<string> {
  const visible = new Set(pinned)
  const queue = [...pinned]
  while (queue.length) {
    const id = queue.pop()!
    if (!expanded.has(id)) continue
    for (const next of out.get(id) ?? []) {
      if (!visible.has(next)) {
        visible.add(next)
        queue.push(next)
      }
    }
  }
  return visible
}

/**
 * Top-down layered layout: callers above callees, so roots sit at the top. Within each row, boxes are
 * ordered under their parent in the order the parent's code refers to them (first call on the left).
 */
export function layout(ids: string[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: 36, ranksep: 90, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const id of ids) g.setNode(id, { width: BOX_W, height: BOX_H })
  for (const e of [...edges].sort((a, b) => a.site - b.site)) g.setEdge(e.src, e.dst)
  dagre.layout(g)

  const pos = new Map<string, { x: number; y: number }>()
  for (const id of ids) {
    const n = g.node(id)
    pos.set(id, { x: n.x - BOX_W / 2, y: n.y - BOX_H / 2 })
  }

  // Dagre orders rows to reduce crossings, which scrambles call order. Re-sort each row, top row first,
  // by (x of the nearest parent above, where that parent refers to it), then reuse the row's x slots.
  const parents = new Map<string, GraphEdge[]>()
  for (const e of edges) parents.set(e.dst, [...(parents.get(e.dst) ?? []), e])
  const rows = new Map<number, string[]>()
  for (const id of ids) {
    const y = Math.round(pos.get(id)!.y)
    rows.set(y, [...(rows.get(y) ?? []), id])
  }
  for (const y of [...rows.keys()].sort((a, b) => a - b)) {
    const row = rows.get(y)!
    const key = (id: string): [number, number] => {
      let best: GraphEdge | null = null
      for (const e of parents.get(id) ?? []) {
        const p = pos.get(e.src)
        if (!p || p.y >= y) continue // only parents in rows above
        const b = best && pos.get(best.src)!
        if (!b || p.y > b.y || (p.y === b.y && p.x < b.x)) best = e
      }
      return best ? [pos.get(best.src)!.x, best.site] : [pos.get(id)!.x, 0]
    }
    const keys = new Map(row.map((id) => [id, key(id)]))
    const slots = row.map((id) => pos.get(id)!.x).sort((a, b) => a - b)
    row.sort((a, b) => keys.get(a)![0] - keys.get(b)![0] || keys.get(a)![1] - keys.get(b)![1])
    row.forEach((id, i) => pos.set(id, { x: slots[i], y: pos.get(id)!.y }))
  }
  return pos
}
