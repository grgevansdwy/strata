import { useCallback, useEffect, useRef, useState } from 'react'
import { api, vscodeUrl } from './api'
import { Breadcrumb } from './components/Breadcrumb'
import { CanvasView } from './components/CanvasView'
import { KindChip } from './components/Kind'
import { RelationRail } from './components/RelationRail'
import { SnippetEditor } from './components/SnippetEditor'
import { Summary } from './components/Summary'
import type { Card, NodeView, RepoInfo, ServerEvent } from './types'
import { useStrataSocket } from './useStrataSocket'

const ROOT = 'repo://'
const idFromUrl = () => new URLSearchParams(location.search).get('id') ?? ROOT

const shortModel = (m: string) => m.replace(/^ollama:/, '').replace(/^claude-/, '')

function ModelsPill({ models }: { models: RepoInfo['models'] }) {
  const part = (label: string, model: string, ready: boolean) =>
    `${label} ${ready ? shortModel(model) + (model.startsWith('ollama:') ? ' (local)' : '') : 'off'}`
  const allReady = models.leaf_ready && models.branch_ready
  return (
    <span
      className={`pill ${allReady ? 'ok' : 'warn'}`}
      title={allReady ? 'Summary models' : 'Claude-backed summaries need ANTHROPIC_API_KEY in backend/.env'}
    >
      {part('fn', models.leaf, models.leaf_ready)} · {part('branches', models.branch, models.branch_ready)}
    </span>
  )
}

const CHILD_LABEL: Record<string, string> = { dir: 'Contents', module: 'Symbols', class: 'Members', function: 'Inner functions' }

export default function App() {
  const [id, setId] = useState(idFromUrl)
  const [view, setView] = useState<NodeView | null>(null)
  const [repo, setRepo] = useState<RepoInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [flash, setFlash] = useState<Set<string>>(new Set())
  const [diskVersion, setDiskVersion] = useState(0)
  const [showSource, setShowSource] = useState(false)
  const idRef = useRef(id)
  idRef.current = id

  const navigate = useCallback((next: string, replace = false) => {
    if (next === idRef.current) return
    history[replace ? 'replaceState' : 'pushState'](null, '', next === ROOT ? '/' : `/?id=${encodeURIComponent(next)}`)
    setNotice(null)
    setShowSource(false)
    setDiskVersion(0)
    setId(next)
  }, [])

  const load = useCallback(async (target: string) => {
    try {
      const v = await api.node(target)
      if (target === idRef.current) {
        setView(v)
        setError(null)
      }
    } catch (e) {
      if (target === idRef.current) setError(String(e))
    }
  }, [])

  useEffect(() => { load(id) }, [id, load])
  useEffect(() => { api.repo().then(setRepo).catch(() => {}) }, [])
  useEffect(() => {
    const onPop = () => setId(idFromUrl())
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  }, [])

  // Escape zooms out one level (when not typing in the editor).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || (e.target as HTMLElement).closest('.cm-editor') || !view) return
      const crumbs = view.breadcrumb
      if (crumbs.length > 1) navigate(crumbs[crumbs.length - 2].id)
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [view, navigate])

  const patchCard = (nodeId: string, fn: (c: Card) => Card) =>
    setView((v) => v && {
      ...v,
      node: v.node.id === nodeId ? { ...v.node, ...fn(v.node) } : v.node,
      children: v.children.map((c) => (c.id === nodeId ? fn(c) : c)),
    })

  const connected = useStrataSocket((e: ServerEvent) => {
    if (e.type === 'summary') {
      const { type: _t, node_id, ...summary } = e
      patchCard(node_id, (c) => ({ ...c, summary, summary_status: 'none' }))
    } else if (e.type === 'summary_error') {
      patchCard(e.node_id, (c) => ({ ...c, summary_status: 'error' }))
    } else if (e.type === 'edges') {
      load(idRef.current)
      api.repo().then(setRepo).catch(() => {})
    } else if (e.type === 'delta') {
      const current = idRef.current
      const ids = new Set([...e.changed, ...e.added])
      setFlash(ids)
      setTimeout(() => setFlash(new Set()), 1600)
      if (e.removed.includes(current) && view) {
        // Zoom out to the nearest ancestor that still exists.
        const alive = [...view.breadcrumb].reverse().find((c) => !e.removed.includes(c.id))
        setNotice(`${view.node.name} no longer exists on disk (renamed or deleted).`)
        if (alive) navigate(alive.id, true)
      } else {
        if (ids.has(current)) setDiskVersion((n) => n + 1)
        load(current)
      }
      api.repo().then(setRepo).catch(() => {})
    }
  })

  const node = view?.node
  const isLeafish = node && (node.kind === 'function' || node.kind === 'class')
  const editorOpen = node && (node.kind === 'function' || showSource)

  return (
    <div className="app">
      <header className="topbar">
        <button className="logo" onClick={() => navigate(ROOT)}>
          <span className="logo-mark" aria-hidden>≡</span> Strata
        </button>
        {repo && <span className="repo-name" title={repo.root}>{repo.name}</span>}
        <span className="spacer" />
        {repo && Object.keys(repo.errors).length > 0 && (
          <span className="pill pill-error" title={Object.entries(repo.errors).map(([f, m]) => `${f}: ${m}`).join('\n')}>
            {Object.keys(repo.errors).length} file(s) with syntax errors
          </span>
        )}
        {repo && <span className={`pill ${repo.resolver === 'done' ? 'ok' : ''}`}>{repo.resolver === 'done' ? 'refs resolved' : 'resolving refs…'}</span>}
        {repo && <ModelsPill models={repo.models} />}
        <span className={`pill ${connected ? 'ok' : 'warn'}`}>{connected ? 'live' : 'offline'}</span>
      </header>

      {view && <Breadcrumb crumbs={view.breadcrumb} onNavigate={navigate} />}
      {notice && <div className="notice">{notice}</div>}
      {error && <div className="notice error">{error}</div>}

      {view && node && (
        <div className="body">
          <main className="canvas" key={node.id}>
            <header className="node-head">
              <div className="node-head-top">
                <KindChip kind={node.kind} />
                <h1 className="node-name">{node.name}</h1>
                {node.summary.title && <span className={`node-title ${node.summary.stale ? 'stale' : ''}`}>{node.summary.title}</span>}
              </div>
              <Summary card={node} />
              {node.signature && !editorOpen && <code className="node-sig">{node.signature}</code>}
              <div className="node-meta">
                {node.file && <span>{node.file}{node.kind !== 'module' ? `:${node.start_line}` : ''}</span>}
                <span>{node.loc} LOC</span>
                {node.callers > 0 && <span>{node.callers} callers</span>}
                {node.changed_recently && <span className="recent">changed this week</span>}
                {node.summary.has_summary && <span className="muted" title="Model that wrote the summary">{node.summary.model}</span>}
                {node.abs_path && node.kind !== 'dir' && !editorOpen && <a href={vscodeUrl(node.abs_path, node.start_line)}>Open in VS Code</a>}
                {(node.kind === 'module' || node.kind === 'class') && (
                  <button className="btn ghost small" onClick={() => setShowSource((s) => !s)}>
                    {showSource ? 'Hide source' : node.kind === 'class' ? 'Edit class source' : 'View module source'}
                  </button>
                )}
              </div>
              {node.summary.entry_points.length > 0 && (
                <div className="entry-points">
                  <span className="muted">Start with</span>
                  {node.summary.entry_points.map((name) => {
                    const child = view.children.find((c) => c.name === name)
                    return child
                      ? <button key={name} className="chip" onClick={() => navigate(child.id)}>{name}</button>
                      : <span key={name} className="chip dead">{name}</span>
                  })}
                </div>
              )}
            </header>

            {editorOpen && (
              <SnippetEditor
                nodeId={node.id}
                editable={!!isLeafish}
                version={diskVersion}
                onSaved={(newId) => newId && navigate(newId, true)}
              />
            )}
            <CanvasView cards={view.children} flash={flash} onOpen={navigate} label={CHILD_LABEL[node.kind]} />
          </main>
          <RelationRail view={view} onNavigate={navigate} />
        </div>
      )}
    </div>
  )
}
