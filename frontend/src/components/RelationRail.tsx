import { useState } from 'react'
import type { NodeView, Relation } from '../types'
import { KindChip } from './Kind'

const SECTIONS: { key: keyof NodeView['relations']; label: string }[] = [
  { key: 'called_by', label: 'Called by' },
  { key: 'calls', label: 'Calls' },
  { key: 'imported_by', label: 'Imported by' },
  { key: 'imports', label: 'Imports' },
]

function Entry({ r, showVia, grouped, onNavigate }: { r: Relation; showVia: boolean; grouped: boolean; onNavigate: (id: string) => void }) {
  const via = grouped ? r.via : `via ${r.via.split('#')[1] ?? r.via.replace('repo://', '')}`
  return (
    <li>
      <button className="rel" onClick={() => onNavigate(r.id)}>
        <span
          className={`tier tier-${r.tier}`}
          title={r.tier === 'resolved' ? 'Resolved: confirmed by Jedi' : 'Inferred: matched from the AST, not confirmed'}
        />
        <KindChip kind={r.node_kind} />
        <span className="rel-body">
          <span className="rel-name">{r.id.split('#')[1] ?? r.name}</span>
          <span className="rel-file">{r.file}{r.node_kind !== 'module' ? `:${r.start_line}` : ''}</span>
          {showVia && via && <span className="rel-via">{via}</span>}
        </span>
      </button>
    </li>
  )
}

const CAP = 12

/** At package level individual functions are noise; group the other side by module instead. */
function groupByFile(items: Relation[]): Relation[] {
  const byFile = new Map<string, { r: Relation; n: number }>()
  for (const r of items) {
    const g = byFile.get(r.file)
    if (g) {
      g.n++
      if (r.tier === 'inferred') g.r = { ...g.r, tier: 'inferred' }
    } else {
      byFile.set(r.file, { r: { ...r, id: `repo://${r.file}`, node_kind: 'module', name: r.file.split('/').pop()!, via: '' }, n: 1 })
    }
  }
  return [...byFile.values()].map(({ r, n }) => ({ ...r, via: n > 1 ? `${n} symbols` : '' }))
}

function Section({ nodeId, label, items, grouped, showVia, onNavigate }: {
  nodeId: string; label: string; items: Relation[]; grouped: boolean; showVia: boolean; onNavigate: (id: string) => void
}) {
  const [all, setAll] = useState(false)
  const rows = grouped ? groupByFile(items) : items
  const shown = all ? rows : rows.slice(0, CAP)
  return (
    <section className="rail-section">
      <h3 className="section-label">{label} <span className="count">{rows.length}{grouped ? ' files' : ''}</span></h3>
      <ul>{shown.map((r) => <Entry key={r.kind + r.id} r={r} showVia={grouped ? !!r.via : showVia && r.via !== nodeId} grouped={grouped} onNavigate={onNavigate} />)}</ul>
      {rows.length > CAP && (
        <button className="btn ghost small rail-more" onClick={() => setAll(!all)}>
          {all ? 'Show less' : `Show all ${rows.length}`}
        </button>
      )}
    </section>
  )
}

export function RelationRail({ view, onNavigate }: { view: NodeView; onNavigate: (id: string) => void }) {
  const aggregated = view.node.kind === 'dir' || view.node.kind === 'module' || view.node.kind === 'class'
  const grouped = view.node.kind === 'dir'
  const total = SECTIONS.reduce((n, s) => n + view.relations[s.key].length, 0)
  return (
    <aside className="rail" key={view.node.id}>
      <h2 className="rail-title">Relationships</h2>
      {aggregated && total > 0 && <p className="rail-note">Everything inside <b>{view.node.name}</b>, crossing its boundary.</p>}
      {SECTIONS.map(({ key, label }) =>
        view.relations[key].length ? (
          <Section key={key} nodeId={view.node.id} label={label} items={view.relations[key]} grouped={grouped} showVia={aggregated} onNavigate={onNavigate} />
        ) : null,
      )}
      {total === 0 && (
        <p className="rail-empty">
          No static relationships found. Decorators, <code>getattr</code>, dependency injection and framework routing
          are invisible to static analysis, so this doesn't mean nothing uses it.
        </p>
      )}
      <div className="legend">
        <span><span className="tier tier-resolved" /> resolved (Jedi)</span>
        <span><span className="tier tier-inferred" /> inferred (AST)</span>
      </div>
    </aside>
  )
}
