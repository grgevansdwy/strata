import type { NodeView } from '../types'
import { KindChip } from './Kind'

export function Breadcrumb({ crumbs, onNavigate }: { crumbs: NodeView['breadcrumb']; onNavigate: (id: string) => void }) {
  return (
    <nav className="breadcrumb" aria-label="Location">
      {crumbs.map((c, i) => {
        const last = i === crumbs.length - 1
        return (
          <span key={c.id} className="crumb-wrap">
            {i > 0 && <span className="crumb-sep">/</span>}
            <button className={`crumb ${last ? 'current' : ''}`} onClick={() => onNavigate(c.id)} disabled={last}>
              {i > 0 && <KindChip kind={c.kind} />}
              <span>{c.name}</span>
            </button>
          </span>
        )
      })}
    </nav>
  )
}
