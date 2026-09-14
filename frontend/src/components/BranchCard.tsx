import type { Card } from '../types'
import { KindChip } from './Kind'
import { Summary } from './Summary'

export function BranchCard({ card, flash, onOpen }: { card: Card; flash: boolean; onOpen: (id: string) => void }) {
  const branch = card.kind !== 'function'
  return (
    <button className={`card kind-border-${card.kind} ${flash ? 'flash' : ''}`} onClick={() => onOpen(card.id)}>
      <div className="card-top">
        <KindChip kind={card.kind} />
        <span className="card-name">{card.name}</span>
        {card.error && <span className="badge badge-error" title={card.error}>syntax error</span>}
        {card.changed_recently && <span className="dot-recent" title="Changed in the last 7 days" />}
      </div>
      {branch && card.summary.title && <div className={`card-title ${card.summary.stale ? 'stale' : ''}`}>{card.summary.title}</div>}
      <Summary card={card} compact />
      {card.signature && card.kind === 'function' && <code className="card-sig">{card.signature}</code>}
      <div className="card-meta">
        <span>{card.loc} LOC</span>
        {card.callers > 0 && <span>{card.callers} caller{card.callers === 1 ? '' : 's'}</span>}
        {branch && card.children > 0 && <span>{card.children} {card.kind === 'dir' ? 'item' : 'member'}{card.children === 1 ? '' : 's'}</span>}
      </div>
    </button>
  )
}
