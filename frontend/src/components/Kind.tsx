import type { Kind } from '../types'

const LABEL: Record<Kind, string> = { class: 'cls', function: 'fn', variable: 'var', import: 'imp', block: 'code' }

export function KindChip({ kind }: { kind: Kind }) {
  return <span className={`kind-chip kind-${kind}`}>{LABEL[kind]}</span>
}
