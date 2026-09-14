export type Kind = 'class' | 'function' | 'variable' | 'import' | 'block'

export interface SummaryView {
  title: string | null
  summary: string | null
  entry_points: string[]
  stale: boolean
  has_summary: boolean
  model?: string
}

export interface GraphNode {
  id: string
  kind: Kind
  name: string
  file: string
  start_line: number
  end_line: number
  loc: number
  signature: string | null // for variables, imports and blocks: their first line of code
  docstring: string | null
  summary: SummaryView
  summary_status: 'none' | 'pending' | 'error' | 'disabled' | 'code'
}

export type EdgeKind = 'call' | 'uses' | 'member'

export interface GraphEdge {
  src: string
  dst: string
  kind: EdgeKind
  tier: 'inferred' | 'resolved'
}

export interface Roots {
  entry: string[]
  functions: string[]
  tests: string[]
  other: string[]
}

export interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  roots: Roots
}

export interface RepoInfo {
  name: string
  root: string
  files: number
  errors: Record<string, string>
  summaries_enabled: boolean
  resolver: 'pending' | 'done' | 'off'
  models: { leaf: string; leaf_ready: boolean; branch: string; branch_ready: boolean }
}

export interface Source {
  source: string
  src_hash: string
  start_line: number
  file: string
  abs_path: string
}

export type ServerEvent =
  | { type: 'delta'; files: string[]; added: string[]; removed: string[]; changed: string[]; errors: Record<string, string> }
  | ({ type: 'summary'; node_id: string } & SummaryView)
  | { type: 'summary_error'; node_id: string; error: string }
  | { type: 'edges' }
