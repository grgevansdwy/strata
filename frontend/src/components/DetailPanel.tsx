import type { GraphEdge, GraphNode } from '../types'
import { KindChip } from './Kind'
import { SnippetEditor } from './SnippetEditor'
import { Summary } from './Summary'

function Links({ title, items, byId, onPick }: {
  title: string
  items: { id: string; kind: GraphEdge['kind'] }[]
  byId: Map<string, GraphNode>
  onPick: (id: string) => void
}) {
  if (!items.length) return null
  return (
    <section>
      <h3 className="section-label">{title}<span className="count">{items.length}</span></h3>
      <ul className="links">
        {items.map(({ id, kind }) => {
          const n = byId.get(id)
          return n ? (
            <li key={id}>
              <button className="link" onClick={() => onPick(id)} title={`${n.file}:${n.start_line}`}>
                <KindChip kind={n.kind} />
                <span className="link-name">{n.name}</span>
                <span className="link-kind">{kind}</span>
              </button>
            </li>
          ) : null
        })}
      </ul>
    </section>
  )
}

export function DetailPanel({ node, outgoing, incoming, byId, version, onClose, onOpenTarget, onOpenSource, onSaved }: {
  node: GraphNode
  outgoing: GraphEdge[]
  incoming: GraphEdge[]
  byId: Map<string, GraphNode>
  version: number
  onClose: () => void
  onOpenTarget: (id: string) => void
  onOpenSource: (id: string) => void
  onSaved: (newId: string | null) => void
}) {
  const editable = node.kind === 'function' || node.kind === 'class'
  return (
    <aside className="detail">
      <header className="detail-head">
        <KindChip kind={node.kind} />
        <h2 className="detail-name">{node.name}</h2>
        <span className="spacer" />
        <button className="btn ghost small" onClick={onClose} title="Close (Esc)">✕</button>
      </header>
      <div className="detail-meta">{node.file}:{node.start_line}–{node.end_line} · {node.loc} lines{node.summary.model ? ` · ${node.summary.model}` : ''}</div>
      {node.summary_status !== 'code' && <Summary node={node} />}
      <SnippetEditor nodeId={node.id} editable={editable} version={version} onSaved={onSaved} />
      <Links title="Points to" items={outgoing.map((e) => ({ id: e.dst, kind: e.kind }))} byId={byId} onPick={onOpenTarget} />
      <Links title="Pointed to by" items={incoming.map((e) => ({ id: e.src, kind: e.kind }))} byId={byId} onPick={onOpenSource} />
    </aside>
  )
}
