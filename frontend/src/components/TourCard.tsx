import type { GraphNode, Tour } from '../types'

export function TourCard({ tour, step, byId, onStep, onExit }: {
  tour: Tour
  step: number
  byId: Map<string, GraphNode>
  onStep: (i: number) => void
  onExit: () => void
}) {
  const current = tour.steps[step]
  const node = byId.get(current.node_id)
  return (
    <div className="tour-card">
      <div className="tour-head">
        <strong>{tour.title}</strong>
        <span className="muted">Step {step + 1} of {tour.steps.length}</span>
        <span className="spacer" />
        <button className="btn ghost small" onClick={onExit} title="Back to the full graph (Esc)">Exit tour</button>
      </div>
      {step === 0 && <p className="tour-overview">{tour.overview}</p>}
      <div className="tour-step">
        <code>{node?.name ?? current.node_id}</code> {current.explanation}
      </div>
      <div className="tour-nav">
        <button className="btn" disabled={step === 0} onClick={() => onStep(step - 1)}>← Back</button>
        <div className="tour-dots">
          {tour.steps.map((_, i) => (
            <button key={i} className={i === step ? 'on' : ''} onClick={() => onStep(i)} title={`Step ${i + 1}`} />
          ))}
        </div>
        <button className="btn primary" disabled={step === tour.steps.length - 1} onClick={() => onStep(step + 1)}>Next →</button>
      </div>
    </div>
  )
}
