import type { GraphNode, Roots } from '../types'
import { KindChip } from './Kind'

const SECTIONS: { key: keyof Roots; label: string; hint: string; open: boolean }[] = [
  { key: 'entry', label: 'Entry points', hint: '__main__ blocks, pyproject scripts, web routes', open: true },
  { key: 'functions', label: 'Uncalled functions', hint: 'Nothing in the repo calls these (or the call is dynamic)', open: true },
  { key: 'tests', label: 'Tests', hint: 'Roots inside test files', open: false },
  { key: 'other', label: 'Unreferenced', hint: 'Classes, variables and module-level code nothing points at', open: false },
]

export function RootList({ roots, byId, pinned, onToggle, onFocus }: {
  roots: Roots
  byId: Map<string, GraphNode>
  pinned: Set<string>
  onToggle: (id: string) => void
  onFocus: (id: string) => void
}) {
  return (
    <div className="roots">
      {SECTIONS.map(({ key, label, hint, open }) => (
        <details key={key} open={open && roots[key].length > 0}>
          <summary title={hint}>{label}<span className="count">{roots[key].length}</span></summary>
          <ul>
            {roots[key].map((id) => {
              const n = byId.get(id)
              if (!n) return null
              return (
                <li key={id} className={pinned.has(id) ? 'on' : ''}>
                  <input type="checkbox" checked={pinned.has(id)} onChange={() => onToggle(id)} title="Show on the graph" />
                  <button onClick={() => onFocus(id)} title={`${n.file}:${n.start_line}`}>
                    <KindChip kind={n.kind} />
                    <span className="root-text">
                      <span className="root-name">{n.name}</span>
                      <span className="root-file">{n.file}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </details>
      ))}
    </div>
  )
}
