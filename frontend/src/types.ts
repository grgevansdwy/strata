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

export type EdgeKind = 'call' | 'uses' | 'member' | 'flow' // flow: tour steps with no direct line

export interface GraphEdge {
  src: string
  dst: string
  kind: EdgeKind
  tier: 'inferred' | 'resolved'
  site: number // line * 10000 + col of the reference in src: children read left to right in this order
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

export interface TourStep {
  node_id: string
  explanation: string
  lines: number[] // absolute line numbers in the box's file
}

export interface Tour {
  title: string
  overview: string
  steps: TourStep[]
}

export type Answer = Tour | { text: string }

export type AskEvent =
  | { type: 'progress'; text: string }
  | ({ type: 'tour' } & Tour)
  | { type: 'answer'; text: string }
  | { type: 'error'; message: string }

export interface Turn {
  question: string
  progress: string[]
  answer?: Answer
  error?: string
}
