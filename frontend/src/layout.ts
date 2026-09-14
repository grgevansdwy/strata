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

/** Top-down layered layout: callers above callees, so roots sit at the top. */
export function layout(ids: string[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: 36, ranksep: 90, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const id of ids) g.setNode(id, { width: BOX_W, height: BOX_H })
  for (const e of edges) g.setEdge(e.src, e.dst)
  dagre.layout(g)
  const pos = new Map<string, { x: number; y: number }>()
  for (const id of ids) {
    const n = g.node(id)
    pos.set(id, { x: n.x - BOX_W / 2, y: n.y - BOX_H / 2 })
  }
  return pos
}
