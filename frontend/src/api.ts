import type { Answer, AskEvent, Graph, RepoInfo, Source } from './types'

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  repo: () => fetch('/api/repo').then((r) => json<RepoInfo>(r)),
  graph: () => fetch('/api/graph').then((r) => json<Graph>(r)),
  requestSummaries: (ids: string[]) =>
    fetch('/api/summaries', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) }),
  /** Streams the guide's progress, then its tour / answer / error. */
  ask: async function* (question: string, history: { question: string; answer: Answer }[], selected: string | null): AsyncGenerator<AskEvent> {
    const r = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history, selected }),
    })
    if (!r.ok || !r.body) throw new Error(`${r.status} ${await r.text()}`)
    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let i
      while ((i = buffer.indexOf('\n')) >= 0) {
        yield JSON.parse(buffer.slice(0, i))
        buffer = buffer.slice(i + 1)
      }
    }
  },
  source: (id: string) => fetch(`/api/source?id=${encodeURIComponent(id)}`).then((r) => json<Source>(r)),
  patch: (id: string, expected_src_hash: string, source: string) =>
    fetch(`/api/node?id=${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_src_hash, source }),
    }),
}

export const vscodeUrl = (absPath: string, line?: number | null) => `vscode://file${absPath}${line ? `:${line}` : ''}`
