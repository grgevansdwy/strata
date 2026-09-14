import type { Kind } from '../types'

const LABEL: Record<Kind, string> = { dir: 'pkg', module: 'mod', class: 'cls', function: 'fn' }

export function KindChip({ kind }: { kind: Kind }) {
  return <span className={`kind-chip kind-${kind}`}>{LABEL[kind]}</span>
}
