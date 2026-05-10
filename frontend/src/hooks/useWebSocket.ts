import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  ClientEvent,
  PermissionAskEvent,
  ServerEvent,
} from '../types/events'

export type WsStatus =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'closed'

interface UseWebSocketResult {
  status: WsStatus
  /** Convenience: status === 'open'. */
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

const BACKOFF_MS = [500, 1_000, 2_000, 5_000, 10_000, 15_000]
const MAX_RETRIES = 20

/**
 * 對單一 session 的 WebSocket 連線。
 *
 * 設計重點:
 * - **Auto-reconnect with exponential backoff**:連線非主動關閉時自動重連,
 *   依靠 server 端的 `_replay_history` (chat.py:84) 把對話狀態補回來,因此
 *   reconnect 後會清空 events 等 server replay。
 * - **Send queue**:reconnecting / connecting 期間 send() 把 message 排隊,
 *   open 時 flush。使用者在連線抖動時打字不會丟失。
 * - **rAF batching for messages**:streaming 期間 onmessage 累積到 ref,
 *   在 requestAnimationFrame 內 flush 一次到 setEvents,避免每個 token
 *   觸發 React render(原本是 O(n²) 拷貝 events 陣列)。
 *
 * `status` 是五態:idle (no session) / connecting / open / reconnecting / closed。
 */
export function useWebSocket(
  sessionId: string | null,
  token: string | null,
): UseWebSocketResult {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sendQueueRef = useRef<ClientEvent[]>([])
  const closingIntentionallyRef = useRef(false)

  // rAF batching for incoming messages
  const pendingEventsRef = useRef<ServerEvent[]>([])
  const rafScheduledRef = useRef(false)

  const [status, setStatus] = useState<WsStatus>('idle')
  const [events, setEvents] = useState<ServerEvent[]>([])
  const [pendingPermissions, setPendingPermissions] = useState<
    PermissionAskEvent[]
  >([])

  const clear = useCallback(() => {
    setEvents([])
    setPendingPermissions([])
    pendingEventsRef.current = []
  }, [])

  const flushPending = useCallback(() => {
    rafScheduledRef.current = false
    if (pendingEventsRef.current.length === 0) return
    const batch = pendingEventsRef.current
    pendingEventsRef.current = []
    setEvents((prev) => prev.concat(batch))
    const newPerms = batch.filter(
      (e): e is PermissionAskEvent => e.type === 'permission_ask',
    )
    if (newPerms.length > 0) {
      setPendingPermissions((prev) => prev.concat(newPerms))
    }
  }, [])

  const scheduleFlush = useCallback(() => {
    if (rafScheduledRef.current) return
    rafScheduledRef.current = true
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(flushPending)
    } else {
      setTimeout(flushPending, 16)
    }
  }, [flushPending])

  useEffect(() => {
    if (!sessionId || !token) {
      // 主動斷線:不觸發 reconnect
      closingIntentionallyRef.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      sendQueueRef.current = []
      pendingEventsRef.current = []
      setStatus('idle')
      return
    }

    // 換 session/token 時 reset retry counter 與 events buffer
    retryRef.current = 0
    closingIntentionallyRef.current = false

    let disposed = false

    const connect = (isReconnect: boolean) => {
      if (disposed) return
      setStatus(isReconnect ? 'reconnecting' : 'connecting')

      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const url = `${proto}//${host}/chat/stream/${sessionId}?token=${encodeURIComponent(
        token,
      )}`

      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (disposed) return
        retryRef.current = 0
        setStatus('open')
        // server 在連線後會 replay history,先清掉前一輪的 events
        // 避免 reconnect 出現重複訊息
        if (isReconnect) {
          pendingEventsRef.current = []
          setEvents([])
          setPendingPermissions([])
        }
        // flush queued sends
        const q = sendQueueRef.current
        sendQueueRef.current = []
        for (const msg of q) {
          try {
            ws.send(JSON.stringify(msg))
          } catch {
            sendQueueRef.current.push(msg)
          }
        }
      }

      ws.onmessage = (e) => {
        if (disposed) return
        let parsed: unknown
        try {
          parsed = JSON.parse(e.data)
        } catch {
          return
        }
        // Server batches replay-history events as a JSON array(一個 frame
        // 包多個 events)— 偵測到 array 就 spread,單 event 走 push。
        if (Array.isArray(parsed)) {
          pendingEventsRef.current.push(...(parsed as ServerEvent[]))
        } else {
          pendingEventsRef.current.push(parsed as ServerEvent)
        }
        scheduleFlush()
      }

      ws.onerror = () => {
        // 真正的 close 由 onclose 處理 — onerror 在 browser 中沒有可靠 detail
      }

      ws.onclose = (event) => {
        if (disposed) return
        wsRef.current = null
        if (closingIntentionallyRef.current) {
          setStatus('closed')
          return
        }
        // 1008 (policy) = token 失效 — 不要重試,讓上層重新登入
        if (event.code === 1008) {
          setStatus('closed')
          return
        }
        const attempt = retryRef.current
        if (attempt >= MAX_RETRIES) {
          setStatus('closed')
          return
        }
        const delay =
          BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 15_000
        retryRef.current = attempt + 1
        setStatus('reconnecting')
        reconnectTimerRef.current = setTimeout(() => connect(true), delay)
      }
    }

    connect(false)

    return () => {
      disposed = true
      closingIntentionallyRef.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      const ws = wsRef.current
      if (ws) {
        // detach handlers BEFORE close — 避免 stale ws 的 onclose / onmessage
        // 在新 ws 已建立後 fire,clobber 新狀態。
        ws.onopen = null
        ws.onclose = null
        ws.onerror = null
        ws.onmessage = null
        ws.close()
        wsRef.current = null
      }
      sendQueueRef.current = []
      pendingEventsRef.current = []
    }
  }, [sessionId, token, scheduleFlush])

  // 換 session → 清訊息(初次連線也會清,reconnect 不清)
  useEffect(() => {
    setEvents([])
    setPendingPermissions([])
    pendingEventsRef.current = []
  }, [sessionId])

  const send = useCallback((msg: ClientEvent) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
      return
    }
    // 連線中 / reconnecting / 暫時關閉 → 排隊
    sendQueueRef.current.push(msg)
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
    status,
    connected: status === 'open',
    events,
    pendingPermissions,
    send,
    answerPermission,
    abort,
    clear,
  }
}
