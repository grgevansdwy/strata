import { useEffect, useRef, useState } from 'react'
import type { ServerEvent } from './types'

/** One WebSocket for the whole app; reconnects with backoff. */
export function useStrataSocket(onEvent: (e: ServerEvent) => void) {
  const handler = useRef(onEvent)
  handler.current = onEvent
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry = 0
    let timer: number | undefined
    let closed = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => {
        retry = 0
        setConnected(true)
      }
      ws.onmessage = (m) => handler.current(JSON.parse(m.data))
      ws.onclose = () => {
        setConnected(false)
        if (!closed) timer = window.setTimeout(connect, Math.min(1000 * 2 ** retry++, 10000))
      }
    }
    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      ws?.close()
    }
  }, [])

  return connected
}
