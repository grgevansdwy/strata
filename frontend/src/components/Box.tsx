import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { GraphNode } from '../types'
import { KindChip } from './Kind'
import { Summary } from './Summary'

export type BoxData = { node: GraphNode; hidden: number; expanded: boolean; selected: boolean; flash: boolean }
export type BoxNode = Node<BoxData, 'box'>

/** One box in the graph. `hidden` counts what this box points at that isn't on screen yet. */
export function Box({ data }: NodeProps<BoxNode>) {
  const { node, hidden, expanded, selected, flash } = data
  return (
    <div className={`box kind-border-${node.kind} ${selected ? 'selected' : ''} ${flash ? 'flash' : ''}`}>
      <Handle type="target" position={Position.Top} className="handle" />
      <div className="box-top">
        <KindChip kind={node.kind} />
        <span className="box-name" title={node.name}>{node.name}</span>
        {hidden > 0 && <span className="box-more" title={`${hidden} more connected — click to show`}>+{hidden}</span>}
        {expanded && hidden === 0 && <span className="box-open" title="Expanded — click again to collapse">−</span>}
      </div>
      <div className="box-file">{node.file}:{node.start_line}</div>
      <Summary node={node} />
      <Handle type="source" position={Position.Bottom} className="handle" />
    </div>
  )
}
