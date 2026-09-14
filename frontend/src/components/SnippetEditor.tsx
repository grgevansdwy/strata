import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { python } from '@codemirror/lang-python'
import { indentUnit } from '@codemirror/language'
import { MergeView } from '@codemirror/merge'
import { EditorSelection, EditorState, type Extension } from '@codemirror/state'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView, highlightActiveLine, keymap, lineNumbers } from '@codemirror/view'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, vscodeUrl } from '../api'
import type { Source } from '../types'

interface Conflict { reason: string; current_source: string | null; current_src_hash: string | null }

const theme = EditorView.theme({
  '&': { backgroundColor: 'var(--code-bg)', fontSize: '12.5px' },
  '.cm-gutters': { backgroundColor: 'var(--code-bg)', borderRight: '1px solid var(--border)' },
  '.cm-content': { fontFamily: 'var(--mono)' },
  '&.cm-focused': { outline: 'none' },
})

function baseExtensions(startLine: number, readOnly: boolean): Extension[] {
  return [
    lineNumbers({ formatNumber: (n) => String(n + startLine - 1) }),
    highlightActiveLine(),
    history(),
    python(),
    indentUnit.of('    '),
    oneDark,
    theme,
    EditorState.readOnly.of(readOnly),
    EditorView.editable.of(!readOnly),
  ]
}

export function SnippetEditor({ nodeId, editable, version, onSaved }: {
  nodeId: string
  editable: boolean
  version: number // bumped when the file changed on disk
  onSaved: (newNodeId: string | null) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const mergeHost = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const [src, setSrc] = useState<Source | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error' | 'warn'; text: string } | null>(null)
  const [conflict, setConflict] = useState<Conflict | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const dirtyRef = useRef(false)
  dirtyRef.current = dirty

  const load = useCallback(async () => {
    try {
      const s = await api.source(nodeId)
      setSrc(s)
      setDirty(false)
      setConflict(null)
      setLoadError(null)
    } catch (e) {
      setLoadError(String(e))
    }
  }, [nodeId])

  useEffect(() => {
    setMessage(null)
    load()
  }, [load])

  // Disk changed underneath us: reload if clean, warn if there are unsaved edits.
  useEffect(() => {
    if (version === 0) return
    if (dirtyRef.current) setMessage({ kind: 'warn', text: 'This code changed on disk. Saving will show a conflict.' })
    else load()
  }, [version, load])

  const save = useCallback(async (expectedHash?: string) => {
    const v = view.current
    if (!v || !src || !editable) return true
    setSaving(true)
    setMessage(null)
    const r = await api.patch(nodeId, expectedHash ?? src.src_hash, v.state.doc.toString())
    setSaving(false)
    const body = await r.json()
    if (r.status === 409) {
      setConflict(body)
    } else if (r.status === 422) {
      setMessage({ kind: 'error', text: body.message + (body.line ? ` (line ${body.line})` : '') })
      if (body.line && body.line <= v.state.doc.lines) {
        const line = v.state.doc.line(body.line)
        v.dispatch({ selection: EditorSelection.cursor(line.from), scrollIntoView: true })
        v.focus()
      }
    } else if (r.ok) {
      setMessage({ kind: 'ok', text: body.changed ? `Saved${body.formatted ? ' and formatted' : ''}` : 'No changes' })
      setConflict(null)
      if (body.node_id && body.node_id !== nodeId) onSaved(body.node_id)
      else await load()
    } else {
      setMessage({ kind: 'error', text: `Save failed: ${r.status}` })
    }
    return true
  }, [nodeId, src, editable, load, onSaved])

  const saveRef = useRef(save)
  saveRef.current = save

  useEffect(() => {
    if (!host.current || !src) return
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: src.source,
        extensions: [
          keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => (saveRef.current(), true) }, indentWithTab, ...defaultKeymap, ...historyKeymap]),
          ...baseExtensions(src.start_line, !editable),
          EditorView.updateListener.of((u) => { if (u.docChanged) setDirty(u.state.doc.toString() !== src.source) }),
        ],
      }),
    })
    view.current = v
    return () => { v.destroy(); view.current = null }
  }, [src, editable])

  useEffect(() => {
    if (!conflict || !mergeHost.current || !view.current) return
    const ro = [python(), oneDark, theme, EditorState.readOnly.of(true), EditorView.editable.of(false)]
    const mv = new MergeView({
      parent: mergeHost.current,
      a: { doc: conflict.current_source ?? '', extensions: ro },
      b: { doc: view.current.state.doc.toString(), extensions: ro },
    })
    return () => mv.destroy()
  }, [conflict])

  if (loadError) return <div className="editor-shell"><div className="editor-msg error">{loadError}</div></div>

  return (
    <section className="editor-shell">
      <div className="editor-bar">
        <span className="editor-file">{src ? `${src.file}:${src.start_line}` : 'loading…'}</span>
        {dirty && <span className="badge badge-dirty">unsaved</span>}
        {!editable && <span className="badge">read-only</span>}
        <span className="spacer" />
        {message && <span className={`editor-msg ${message.kind}`}>{message.text}</span>}
        {src && <a className="btn ghost" href={vscodeUrl(src.abs_path, src.start_line)}>Open in VS Code</a>}
        {editable && (
          <>
            <button className="btn ghost" disabled={!dirty || saving} onClick={load}>Revert</button>
            <button className="btn primary" disabled={!dirty || saving} onClick={() => save()}>
              {saving ? 'Saving…' : 'Save'} <kbd>⌘S</kbd>
            </button>
          </>
        )}
      </div>
      {conflict && (
        <div className="conflict">
          <div className="conflict-head">
            <strong>Conflict: {conflict.reason}.</strong> Nothing was written.
            {conflict.current_source !== null && <span className="muted"> Left is on disk, right is yours.</span>}
          </div>
          {conflict.current_source !== null && <div className="merge" ref={mergeHost} />}
          <div className="conflict-actions">
            <button className="btn" onClick={load}>Discard mine, load disk version</button>
            {conflict.current_src_hash && (
              <button className="btn danger" onClick={() => save(conflict.current_src_hash!)}>Overwrite disk with mine</button>
            )}
            <button className="btn ghost" onClick={() => setConflict(null)}>Keep editing</button>
          </div>
        </div>
      )}
      <div className="editor" ref={host} />
    </section>
  )
}
