import { Background, Controls, MarkerType, ReactFlow, ReactFlowProvider, useReactFlow, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { AskPanel } from './components/AskPanel'
import { Box, type BoxNode } from './components/Box'
import { DetailPanel } from './components/DetailPanel'
import { RootList } from './components/RootList'
import { TourCard } from './components/TourCard'
import { BOX_H, BOX_W, layout, visibleIds } from './layout'
import type { Answer, Graph, GraphEdge, GraphNode, RepoInfo, ServerEvent, Tour, Turn } from './types'
import { useStrataSocket } from './useStrataSocket'

const shortModel = (m: string) => m.replace(/^(ollama|openai):/, '').replace(/^claude-/, '')
const DESCRIBED = new Set(['function', 'class'])
const nodeTypes = { box: Box }

function ModelsPill({ models }: { models: RepoInfo['models'] }) {
  const part = (label: string, model: string, ready: boolean) =>
    `${label} ${ready ? shortModel(model) + (/^(ollama|openai):/.test(model) ? ' (local)' : '') : 'off'}`
  const allReady = models.leaf_ready && models.branch_ready
  return (
    <span className={`pill ${allReady ? 'ok' : 'warn'}`} title={allReady ? 'Description models' : 'Set STRATA_LEAF_MODEL / STRATA_BRANCH_MODEL in backend/.env'}>
      {part('fn', models.leaf, models.leaf_ready)} · {part('classes', models.branch, models.branch_ready)}
    </span>
  )
}

function Strata() {
  const [graph, setGraph] = useState<Graph | null>(null)
  const [repo, setRepo] = useState<RepoInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pinned, setPinned] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(null)
  const [flash, setFlash] = useState<Set<string>>(new Set())
  const [diskVersion, setDiskVersion] = useState(0)
  const [tab, setTab] = useState<'roots' | 'ask'>('roots')
  const [turns, setTurns] = useState<Turn[]>([])
  const [running, setRunning] = useState(false)
  const [tour, setTour] = useState<Tour | null>(null)
  const [step, setStep] = useState(0)
  const tourRef = useRef(tour)
  tourRef.current = tour
  const requested = useRef(new Set<string>())
  const selectedRef = useRef(selected)
  selectedRef.current = selected
  const flow = useReactFlow()

  const load = useCallback(async () => {
    try {
      const g = await api.graph()
      setError(null)
      setGraph(g)
      const alive = new Set(g.nodes.map((n) => n.id))
      const keep = (s: Set<string>) => new Set([...s].filter((id) => alive.has(id)))
      setPinned((p) => (p.size ? keep(p) : new Set(g.roots.entry.length ? g.roots.entry : g.roots.functions.slice(0, 8))))
      setExpanded(keep)
      setSelected((s) => (s && alive.has(s) ? s : null))
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { api.repo().then(setRepo).catch(() => {}) }, [])

  const { byId, out, incoming, outEdges } = useMemo(() => {
    const byId = new Map<string, GraphNode>()
    const out = new Map<string, string[]>()
    const incoming = new Map<string, GraphEdge[]>()
    const outEdges = new Map<string, GraphEdge[]>()
    for (const n of graph?.nodes ?? []) byId.set(n.id, n)
    for (const e of graph?.edges ?? []) {
      out.set(e.src, [...(out.get(e.src) ?? []), e.dst])
      outEdges.set(e.src, [...(outEdges.get(e.src) ?? []), e])
      incoming.set(e.dst, [...(incoming.get(e.dst) ?? []), e])
    }
    for (const list of outEdges.values()) list.sort((a, b) => a.site - b.site) // code order, like the graph
    return { byId, out, incoming, outEdges }
  }, [graph])

  const explored = useMemo(() => visibleIds(pinned, expanded, out), [pinned, expanded, out])
  // A tour replaces the explored graph with just its boxes; exiting brings the explored graph back as it was.
  const visible = useMemo(
    () => (tour ? new Set(tour.steps.map((s) => s.node_id).filter((id) => byId.has(id))) : explored),
    [tour, explored, byId],
  )

  const patchNodes = (ids: Set<string>, fn: (n: GraphNode) => GraphNode) =>
    setGraph((g) => g && { ...g, nodes: g.nodes.map((n) => (ids.has(n.id) ? fn(n) : n)) })

  // Ask the model to describe the boxes on screen; results arrive over the socket.
  useEffect(() => {
    const ids = [...visible].filter((id) => {
      const n = byId.get(id)
      return n && DESCRIBED.has(n.kind) && (!n.summary.has_summary || n.summary.stale) && n.summary_status === 'none' && !requested.current.has(id)
    })
    if (!ids.length) return
    ids.forEach((id) => requested.current.add(id))
    api.requestSummaries(ids).catch(() => {})
    patchNodes(new Set(ids), (n) => ({ ...n, summary_status: 'pending' }))
  }, [visible, byId])

  const connected = useStrataSocket((e: ServerEvent) => {
    if (e.type === 'summary') {
      const { type: _t, node_id, ...summary } = e
      requested.current.delete(node_id)
      patchNodes(new Set([node_id]), (n) => ({ ...n, summary, summary_status: 'none' }))
    } else if (e.type === 'summary_error') {
      patchNodes(new Set([e.node_id]), (n) => ({ ...n, summary_status: 'error' }))
    } else if (e.type === 'edges') {
      load()
      api.repo().then(setRepo).catch(() => {})
    } else if (e.type === 'delta') {
      const touched = new Set([...e.changed, ...e.added])
      setFlash(touched)
      setTimeout(() => setFlash(new Set()), 1600)
      if (selectedRef.current && touched.has(selectedRef.current)) setDiskVersion((v) => v + 1)
      load()
      api.repo().then(setRepo).catch(() => {})
    }
  })

  const toggle = (set: Set<string>, id: string, on?: boolean) => {
    const next = new Set(set)
    if (on ?? !next.has(id)) next.add(id)
    else next.delete(id)
    return next
  }

  const centerOn = useCallback((id: string) => {
    // Two frames: one for the new layout, one for the canvas resizing when the detail panel opens.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const n = flow.getNode(id)
      if (n) flow.setCenter(n.position.x + BOX_W / 2, n.position.y + BOX_H / 2, { zoom: Math.max(flow.getZoom(), 0.8), duration: 300 })
    }))
  }, [flow])

  /** Show a box (pinning it if nothing on screen leads to it), select it and open what it points at. */
  const open = useCallback((id: string) => {
    setTour(null)
    if (!explored.has(id)) setPinned((p) => toggle(p, id, true))
    setExpanded((x) => toggle(x, id, true))
    setSelected(id)
    centerOn(id)
  }, [explored, centerOn])

  const goStep = useCallback((t: Tour, i: number) => {
    setTour(t)
    setStep(i)
    setSelected(t.steps[i].node_id)
    centerOn(t.steps[i].node_id)
  }, [centerOn])

  const exitTour = () => {
    setTour(null)
    setSelected(null)
  }

  const ask = async (question: string) => {
    const history = turns.filter((t) => t.answer).map((t) => ({ question: t.question, answer: t.answer as Answer }))
    const index = turns.length
    const update = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t, i) => (i === index ? fn(t) : t)))
    setTurns((ts) => [...ts, { question, progress: [] }])
    setRunning(true)
    try {
      for await (const e of api.ask(question, history, selected)) {
        if (e.type === 'progress') update((t) => ({ ...t, progress: [...t.progress, e.text] }))
        else if (e.type === 'answer') update((t) => ({ ...t, answer: { text: e.text } }))
        else if (e.type === 'error') update((t) => ({ ...t, error: e.message }))
        else {
          const { type: _t, ...answer } = e
          update((t) => ({ ...t, answer }))
          goStep(answer, 0)
        }
      }
    } catch (err) {
      update((t) => ({ ...t, error: String(err) }))
    } finally {
      setRunning(false)
    }
  }

  const onBoxClick = (id: string) => {
    if (tour) {
      const i = tour.steps.findIndex((s) => s.node_id === id)
      if (i >= 0) goStep(tour, i)
      return
    }
    if (selected === id) setExpanded((x) => toggle(x, id)) // second click collapses / re-expands
    else {
      setSelected(id)
      setExpanded((x) => toggle(x, id, true))
    }
    centerOn(id)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || (e.target as HTMLElement).closest('.cm-editor, textarea')) return
      if (tourRef.current) setTour(null)
      setSelected(null)
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [])

  const { nodes, edges } = useMemo(() => {
    if (!graph) return { nodes: [] as BoxNode[], edges: [] as Edge[] }
    const ids = [...visible].filter((id) => byId.has(id))
    const shown = graph.edges.filter((e) => visible.has(e.src) && visible.has(e.dst))
    // In a tour, consecutive steps without a direct line still get one, so the path reads top to bottom.
    tour?.steps.slice(1).forEach((s, i) => {
      const prev = tour.steps[i].node_id
      if (prev !== s.node_id && !shown.some((e) => (e.src === prev && e.dst === s.node_id) || (e.src === s.node_id && e.dst === prev))) {
        shown.push({ src: prev, dst: s.node_id, kind: 'flow', tier: 'inferred', site: i })
      }
    })
    const stepOf = new Map<string, number>()
    tour?.steps.forEach((s, i) => { if (!stepOf.has(s.node_id)) stepOf.set(s.node_id, i + 1) })
    const pos = layout(ids, shown)
    const nodes: BoxNode[] = ids.map((id) => ({
      id,
      type: 'box',
      position: pos.get(id)!,
      width: BOX_W,
      height: BOX_H,
      data: {
        node: byId.get(id)!,
        hidden: (out.get(id) ?? []).filter((d) => !visible.has(d)).length,
        expanded: expanded.has(id),
        selected: selected === id,
        flash: flash.has(id),
        step: stepOf.get(id),
      },
    }))
    const edges: Edge[] = shown.map((e) => {
      const hot = selected !== null && (e.src === selected || e.dst === selected)
      return {
        id: `${e.src}->${e.dst}`,
        source: e.src,
        target: e.dst,
        className: `edge-${e.kind} ${hot ? 'hot' : ''}`,
        animated: hot,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      }
    })
    return { nodes, edges }
  }, [graph, visible, byId, out, expanded, selected, flash, tour])

  const selectedNode = selected ? byId.get(selected) : undefined
  const tourStep = tour && tour.steps[step]?.node_id === selected ? tour.steps[step] : undefined

  return (
    <div className="app">
      <header className="topbar">
        <span className="logo"><span className="logo-mark" aria-hidden>≡</span> Strata</span>
        {repo && <span className="repo-name" title={repo.root}>{repo.name}</span>}
        {graph && <span className="muted small">{graph.nodes.length} boxes · {graph.edges.length} lines · {visible.size} shown</span>}
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
      {error && <div className="notice error">{error}</div>}

      <div className={`body ${selectedNode ? 'with-detail' : ''}`}>
        <aside className="sidebar">
          <div className="tabs">
            <button className={tab === 'roots' ? 'on' : ''} onClick={() => setTab('roots')}>Roots</button>
            <button className={tab === 'ask' ? 'on' : ''} onClick={() => setTab('ask')}>Ask{running ? ' ·' : ''}</button>
          </div>
          {graph && tab === 'roots' && (
            <RootList
              roots={graph.roots}
              byId={byId}
              pinned={pinned}
              onToggle={(id) => { setTour(null); setPinned((p) => toggle(p, id)) }}
              onFocus={open}
            />
          )}
          {tab === 'ask' && (
            <AskPanel
              turns={turns}
              running={running}
              selected={selectedNode}
              onAsk={ask}
              onOpenTour={(t) => goStep(t, 0)}
              onClearSelection={() => { setTour(null); setSelected(null) }}
            />
          )}
        </aside>
        <main className="graph">
          {/* Mounted once boxes exist, so fitView frames the first graph rather than an empty one. */}
          {nodes.length > 0 && <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeClick={(_, n) => onBoxClick(n.id)}
            onPaneClick={() => { if (!tour) setSelected(null) }}
            nodesDraggable={false}
            nodesConnectable={false}
            colorMode="dark"
            minZoom={0.1}
            fitView
            fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={24} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>}
          {graph && nodes.length === 0 && <div className="graph-empty">Tick a root on the left to start.</div>}
          <div className="legend">
            <span><i className="line call" /> calls</span>
            <span><i className="line uses" /> uses</span>
            <span><i className="line member" /> defines</span>
            {tour && <span><i className="line flow" /> tour path</span>}
            <span className="muted">{tour ? 'click a numbered box to jump to that step' : 'click a box to open it · click again to collapse'}</span>
          </div>
          {tour && <TourCard tour={tour} step={step} byId={byId} onStep={(i) => goStep(tour, i)} onExit={exitTour} />}
        </main>
        {selectedNode && (
          <DetailPanel
            key={`${selectedNode.id}:${tourStep ? step : ''}`}
            node={selectedNode}
            note={tourStep?.explanation}
            highlight={tourStep?.lines}
            outgoing={outEdges.get(selectedNode.id) ?? []}
            incoming={incoming.get(selectedNode.id) ?? []}
            byId={byId}
            version={diskVersion}
            onClose={() => (tour ? exitTour() : setSelected(null))}
            onOpenTarget={open}
            onOpenSource={open}
            onSaved={(newId) => newId && setSelected(newId)}
          />
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Strata />
    </ReactFlowProvider>
  )
}
