import type { GraphNode } from '../types'

/** Description with honest states: stale is dimmed and flagged, missing says why, never invented. */
export function Summary({ node }: { node: GraphNode }) {
  const s = node.summary
  const pending = node.summary_status === 'pending'
  if (node.summary_status === 'code') {
    return <code className="summary code-line">{node.signature}</code>
  }
  if (s.has_summary) {
    return (
      <div className={`summary ${s.stale ? 'stale' : ''}`}>
        {s.stale && (
          <span className="badge badge-stale" title="The code changed since this description was written">
            {pending ? 'refreshing' : 'stale'}
          </span>
        )}
        <span>{s.title ? `${s.title}: ${s.summary}` : s.summary}</span>
      </div>
    )
  }
  if (pending) return <div className="summary pending"><span className="shimmer">Describing…</span></div>
  if (node.summary_status === 'error') return <div className="summary muted">Description failed. Read the code.</div>
  if (node.docstring) {
    return (
      <div className="summary docstring" title="From the docstring, not the model">
        <span className="badge badge-doc">doc</span>
        <span>{node.docstring}</span>
      </div>
    )
  }
  if (node.summary_status === 'disabled') return <div className="summary muted">No model configured in backend/.env</div>
  return <div className="summary muted">No description yet</div>
}
