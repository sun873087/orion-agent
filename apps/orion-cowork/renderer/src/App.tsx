import { useEffect, useRef, useState } from 'react'
import { createConversation, sendPrompt, type SidecarEvent } from './api/agent'

type Message = {
  role: 'user' | 'assistant' | 'system'
  text: string
}

export function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const streamingRef = useRef<string>('')

  useEffect(() => {
    let cancelled = false
    createConversation()
      .then((sid) => {
        if (!cancelled) setSessionId(sid)
      })
      .catch((e) => {
        if (!cancelled) setError(`failed to init: ${String(e)}`)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSend() {
    if (!sessionId || !input.trim() || busy) return
    const userText = input
    setInput('')
    setMessages((m) => [...m, { role: 'user', text: userText }])
    streamingRef.current = ''
    setMessages((m) => [...m, { role: 'assistant', text: '' }])
    setBusy(true)
    setError(null)
    try {
      await sendPrompt(sessionId, userText, (ev: SidecarEvent) => {
        if (ev.event === 'text_delta') {
          const data = ev.data as { text: string }
          streamingRef.current += data.text
          setMessages((m) => {
            const next = [...m]
            next[next.length - 1] = { role: 'assistant', text: streamingRef.current }
            return next
          })
        } else if (ev.event === 'tool_result') {
          const data = ev.data as { tool_name: string; is_error: boolean; text: string }
          const marker = data.is_error ? '✗' : '✓'
          setMessages((m) => [
            ...m,
            { role: 'system', text: `${marker} ${data.tool_name}: ${data.text.slice(0, 200)}` },
          ])
        } else if (ev.event === 'loop_terminated') {
          const data = ev.data as { reason: string; total_turns: number }
          setMessages((m) => [
            ...m,
            { role: 'system', text: `— loop terminated (${data.reason}, turns=${data.total_turns}) —` },
          ])
        }
      })
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ fontFamily: 'system-ui', padding: 16, maxWidth: 900, margin: '0 auto' }}>
      <h2>Orion Cowork (Phase E PoC)</h2>
      <p style={{ color: '#666', fontSize: 13 }}>
        session: <code>{sessionId ?? '(initializing…)'}</code>
      </p>
      {error && <div style={{ background: '#fee', padding: 8, color: '#900' }}>{error}</div>}
      <div
        style={{
          border: '1px solid #ddd',
          padding: 12,
          minHeight: 400,
          maxHeight: 500,
          overflowY: 'auto',
          marginBottom: 12,
        }}
      >
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              marginBottom: 8,
              color: m.role === 'user' ? '#06c' : m.role === 'system' ? '#888' : '#222',
              whiteSpace: 'pre-wrap',
            }}
          >
            <strong>{m.role}:</strong> {m.text}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          style={{ flex: 1, padding: 8 }}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          disabled={!sessionId || busy}
          placeholder={busy ? 'agent thinking…' : 'type a message'}
        />
        <button onClick={handleSend} disabled={!sessionId || busy}>
          Send
        </button>
      </div>
    </div>
  )
}
