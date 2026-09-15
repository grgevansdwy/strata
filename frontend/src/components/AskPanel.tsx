import { useEffect, useRef, useState } from 'react'
import type { GraphNode, Tour, Turn } from '../types'

const isTour = (a: Turn['answer']): a is Tour => !!a && 'steps' in a

/** The guide's conversation. Each question streams progress, then a tour (opened on the graph) or text. */
export function AskPanel({ turns, running, selected, onAsk, onOpenTour, onClearSelection }: {
  turns: Turn[]
  running: boolean
  selected: GraphNode | undefined
  onAsk: (question: string) => void
  onOpenTour: (tour: Tour) => void
  onClearSelection: () => void
}) {
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [turns])

  const submit = () => {
    const q = draft.trim()
    if (!q || running) return
    onAsk(q)
    setDraft('')
  }

  return (
    <div className="ask">
      <div className="ask-log">
        {turns.length === 0 && (
          <p className="muted ask-hint">
            Ask how something works, e.g. “how does a request flow from the GUI to the agent?”. The guide reads the
            code and walks you through the boxes that matter.
          </p>
        )}
        {turns.map((t, i) => (
          <div key={i} className="turn">
            <div className="turn-q">{t.question}</div>
            {!t.answer && !t.error && (
              <ul className="turn-progress">
                {t.progress.map((p, j) => <li key={j}>{p}</li>)}
                {running && i === turns.length - 1 && <li className="shimmer">Thinking…</li>}
              </ul>
            )}
            {t.error && <div className="turn-error">{t.error}</div>}
            {isTour(t.answer) && (
              <button className="turn-tour" onClick={() => onOpenTour(t.answer as Tour)}>
                <strong>{t.answer.title}</strong>
                <span>{t.answer.overview}</span>
                <span className="turn-open">{t.answer.steps.length} steps · open tour →</span>
              </button>
            )}
            {t.answer && !isTour(t.answer) && <div className="turn-text">{t.answer.text}</div>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <div className="ask-input">
        {selected && (
          <span className="ask-about" title="Questions about “this” refer to the selected box">
            about <code>{selected.name}</code>
            <button onClick={onClearSelection} title="Don't ask about this box">✕</button>
          </span>
        )}
        <textarea
          value={draft}
          placeholder={turns.length ? 'Ask a follow-up…' : 'Ask about the code…'}
          rows={3}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
        />
        <button className="btn primary" disabled={running || !draft.trim()} onClick={submit}>{running ? 'Working…' : 'Ask'}</button>
      </div>
    </div>
  )
}
