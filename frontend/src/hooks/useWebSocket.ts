import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  ClientEvent,
  PermissionAskEvent,
  ServerEvent,
} from '../types/events'

interface UseWebSocketResult {
  connected: boolean
  events: ServerEvent[]
  pendingPermissions: PermissionAskEvent[]
  send: (msg: ClientEvent) => void
  answerPermission: (
    requestId: string,
    decision: 'allow' | 'always_allow' | 'deny' | 'always_deny',
  ) => void
  abort: () => void
  clear: () => void
}

/**
 * 對單一 session 的 WebSocket 連線。換 sessionId / token 自動 reconnect。
 *
 * `events` 是累積的 server events list;UI 用此渲染訊息流。
 * `pendingPermissions` 是還沒 decided 的 permission_ask 列表(顯示對話框用)。
 */
export function useWebSocket(
  sessionId: string | null,
  token: string | null,
): UseWebSocketResult {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [events, setEvents] = useState<ServerEvent[]>([])
  const [pendingPermissions, setPendingPermissions] = useState<
    PermissionAskEvent[]
  >([])

  const clear = useCallback(() => {
    setEvents([])
    setPendingPermissions([])
  }, [])

  useEffect(() => {
    if (!sessionId || !token) {
      // 沒 session/token,確保 ws 關
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      setConnected(false)
      return
    }

    // 同 origin 走 vite proxy(`/chat/...` ws);換為相對路徑
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const url = `${proto}//${host}/chat/stream/${sessionId}?token=${encodeURIComponent(
      token,
    )}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => {
      // 由 onclose 處理 setConnected;這裡保留 hook for 偵錯
    }
    ws.onmessage = (e) => {
      let parsed: ServerEvent
      try {
        parsed = JSON.parse(e.data) as ServerEvent
      } catch {
        return
      }
      setEvents((prev) => [...prev, parsed])
      if (parsed.type === 'permission_ask') {
        setPendingPermissions((prev) => [...prev, parsed])
      }
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [sessionId, token])

  // 換 session → 清訊息
  useEffect(() => {
    setEvents([])
    setPendingPermissions([])
  }, [sessionId])

  const send = useCallback((msg: ClientEvent) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify(msg))
  }, [])

  const answerPermission = useCallback(
    (
      requestId: string,
      decision: 'allow' | 'always_allow' | 'deny' | 'always_deny',
    ) => {
      send({ type: 'permission_decision', request_id: requestId, decision })
      setPendingPermissions((prev) =>
        prev.filter((p) => p.request_id !== requestId),
      )
    },
    [send],
  )

  const abort = useCallback(() => {
    send({ type: 'abort' })
  }, [send])

  return {
    connected,
    events,
    pendingPermissions,
    send,
    answerPermission,
    abort,
    clear,
  }
}
