/**
 * Renderer-side wrapper of window.agent.call。
 *
 * 對外:
 *   - createConversation({ provider, model }) → session_id
 *   - sendPrompt(session_id, prompt, onEvent) → 等 turn 完成
 *   - abort(session_id)
 */

export type SidecarEvent =
  | { event: 'text_delta'; data: { text: string } }
  | { event: 'thinking_delta'; data: { text: string } }
  | { event: 'turn_complete'; data: Record<string, never> }
  | {
      event: 'tool_progress'
      data: { tool_name: string; tool_use_id: string; progress: unknown }
    }
  | {
      event: 'tool_error'
      data: { tool_name: string; tool_use_id: string; message: string }
    }
  | {
      event: 'tool_result'
      data: { tool_name: string; tool_use_id: string; is_error: boolean; text: string }
    }
  | { event: 'loop_terminated'; data: { reason: string; total_turns: number } }
  | { event: string; data?: unknown; final?: boolean }

export async function createConversation(
  provider = 'anthropic',
  model = 'claude-sonnet-4-6',
): Promise<string> {
  let sessionId = ''
  await window.agent.call('conversation.create', { provider, model }, (frame) => {
    const data = (frame.data ?? {}) as { session_id?: string }
    if (data.session_id) sessionId = data.session_id
  })
  if (!sessionId) throw new Error('conversation.create returned no session_id')
  return sessionId
}

export async function sendPrompt(
  sessionId: string,
  prompt: string,
  onEvent: (ev: SidecarEvent) => void,
): Promise<void> {
  await window.agent.call(
    'conversation.send',
    { session_id: sessionId, prompt },
    (frame) => {
      onEvent(frame as unknown as SidecarEvent)
    },
  )
}

export async function abort(sessionId: string): Promise<void> {
  await window.agent.call('conversation.abort', { session_id: sessionId }, () => {})
}
