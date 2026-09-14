export type Kind = 'dir' | 'module' | 'class' | 'function'

export interface SummaryView {
  title: string | null
  summary: string | null
  entry_points: string[]
  stale: boolean
  has_summary: boolean
  model?: string
}

export interface Card {
  id: string
  kind: Kind
  name: string
  file: string | null
  start_line: number | null
  end_line: number | null
  loc: number
  signature: string | null
  docstring: string | null
  callers: number
  children: number
  changed_recently: boolean
  summary: SummaryView
  summary_status: 'none' | 'pending' | 'error' | 'disabled'
  error: string | null
  abs_path?: string
}

export interface Relation {
  kind: 'call' | 'import'
  id: string
  via: string
  node_kind: Kind
  name: string
  file: string
  start_line: number
  tier: 'inferred' | 'resolved'
}

export interface NodeView {
  node: Card
  breadcrumb: { id: string; name: string; kind: Kind }[]
  children: Card[]
  relations: { calls: Relation[]; called_by: Relation[]; imports: Relation[]; imported_by: Relation[] }
}

export interface RepoInfo {
  name: string
  root: string
  files: number
  errors: Record<string, string>
  summaries_enabled: boolean
  resolver: 'pending' | 'done' | 'off'
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
