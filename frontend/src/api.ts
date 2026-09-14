import type { NodeView, RepoInfo, Source } from './types'

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  repo: () => fetch('/api/repo').then((r) => json<RepoInfo>(r)),
  node: (id: string) => fetch(`/api/node?id=${encodeURIComponent(id)}`).then((r) => json<NodeView>(r)),
  source: (id: string) => fetch(`/api/source?id=${encodeURIComponent(id)}`).then((r) => json<Source>(r)),
  patch: (id: string, expected_src_hash: string, source: string) =>
    fetch(`/api/node?id=${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_src_hash, source }),
    }),
}

export const vscodeUrl = (absPath: string, line?: number | null) => `vscode://file${absPath}${line ? `:${line}` : ''}`
