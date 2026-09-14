import type { Card } from '../types'
import { BranchCard } from './BranchCard'

export function CanvasView({ cards, flash, onOpen, label }: {
  cards: Card[]; flash: Set<string>; onOpen: (id: string) => void; label: string
}) {
  if (!cards.length) return null
  return (
    <section className="canvas-section">
      <h3 className="section-label">{label} <span className="count">{cards.length}</span></h3>
      <div className="card-grid">
        {cards.map((c) => <BranchCard key={c.id} card={c} flash={flash.has(c.id)} onOpen={onOpen} />)}
      </div>
    </section>
  )
}
