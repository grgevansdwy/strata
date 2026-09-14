import type { Card } from '../types'

/** Summary text with honest states: stale is dimmed and flagged, missing says why, never invented. */
export function Summary({ card, compact = false }: { card: Card; compact?: boolean }) {
  const s = card.summary
  const pending = card.summary_status === 'pending'
  if (s.has_summary) {
    return (
      <div className={`summary ${s.stale ? 'stale' : ''}`}>
        {s.stale && (
          <span className="badge badge-stale" title="The code changed since this summary was written">
            {pending ? 'refreshing' : 'stale'}
          </span>
        )}
        <span>{s.summary}</span>
      </div>
    )
  }
  if (pending) return <div className="summary pending"><span className="shimmer">Summarizing…</span></div>
  if (card.summary_status === 'error') return <div className="summary muted">Summary failed. Read the code.</div>
  if (card.docstring) {
    return (
      <div className="summary docstring" title="From the docstring, not an AI summary">
        <span className="badge badge-doc">doc</span>
        <span>{card.docstring}</span>
      </div>
    )
  }
  if (compact) return <div className="summary muted">—</div>
  return (
    <div className="summary muted">
      {card.summary_status === 'disabled' ? 'No summary: add ANTHROPIC_API_KEY to backend/.env' : 'No summary yet'}
    </div>
  )
}
