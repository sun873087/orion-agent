/**
 * 把 WS ServerEvent 串流 reduce 成可渲染的 FlowEntry 列表。
 *
 * 重點:**連續的工具呼叫併進同一個 tool_group**,即使中間隔著 turn_complete
 * (agentic loop 常一個 turn 只呼一個工具就 end_turn 拿結果、下個 turn 再呼下一個)。
 * 只有 assistant「文字」(模型真的開口說話)才會切斷 group。中間那些工具型 turn 的
 * turn_complete(token 行)會被移除,讓整段工具動作收成一張折疊卡(對齊 Cowork)。
 */
import type { ServerEvent } from '../types/events'
import type { ToolGroupItem } from './toolNarration'

export type FlowEntry =
  | { kind: 'user'; id: string; text: string }
  | { kind: 'assistant'; id: string; text: string }
  | { kind: 'thinking'; id: string; text: string }
  | { kind: 'tool_group'; id: string; items: ToolGroupItem[] }
  | {
      kind: 'turn_complete'
      id: string
      stop_reason: string
      input_tokens: number
      output_tokens: number
    }
  | { kind: 'terminal'; id: string; reason: string; total_turns: number }
  | { kind: 'error'; id: string; message: string }

export interface FlowState {
  entries: FlowEntry[]
  liveAssistant: string
  liveThinking: string
  inFlight: boolean
  notice: 'budget' | 'autocompact' | null
}

export const EMPTY: FlowState = {
  entries: [],
  liveAssistant: '',
  liveThinking: '',
  inFlight: false,
  notice: null,
}

let _flowId = 0
export const newId = (): string => `f${++_flowId}`

function flushLive(
  entries: FlowEntry[],
  liveAssistant: string,
  liveThinking: string,
): FlowEntry[] {
  const out = [...entries]
  if (liveAssistant.trim()) {
    out.push({ kind: 'assistant', id: newId(), text: liveAssistant })
  }
  if (liveThinking.trim()) {
    out.push({ kind: 'thinking', id: newId(), text: liveThinking })
  }
  return out
}

/**
 * 從尾端往回找可併入的 tool_group:沿途只允許跳過 turn_complete(工具型 turn 邊界);
 * 一遇到文字 / user / error / terminal 就停(視為新一段對話,不再併)。
 * 回 group 的 index,或 -1。
 */
function mergeableGroupIndex(entries: FlowEntry[]): number {
  for (let i = entries.length - 1; i >= 0; i--) {
    const kind = entries[i]!.kind
    if (kind === 'tool_group') return i
    if (kind === 'turn_complete') continue
    return -1
  }
  return -1
}

export function reduce(state: FlowState, ev: ServerEvent): FlowState {
  switch (ev.type) {
    case 'user_text': {
      const entries = flushLive(
        state.entries,
        state.liveAssistant,
        state.liveThinking,
      )
      entries.push({ kind: 'user', id: newId(), text: ev.text })
      return { ...state, entries, liveAssistant: '', liveThinking: '' }
    }
    case 'history_replay_done':
      return {
        ...state,
        entries: flushLive(
          state.entries,
          state.liveAssistant,
          state.liveThinking,
        ),
        liveAssistant: '',
        liveThinking: '',
        inFlight: false,
      }
    case 'assistant_text':
      return { ...state, liveAssistant: state.liveAssistant + ev.text }
    case 'assistant_thinking':
      return { ...state, liveThinking: state.liveThinking + ev.text }
    case 'tool_use': {
      const entries = flushLive(
        state.entries,
        state.liveAssistant,
        state.liveThinking,
      )
      const newItem: ToolGroupItem = {
        toolUseId: ev.tool_use_id,
        toolName: ev.tool_name,
        input: ev.input,
      }
      const gi = mergeableGroupIndex(entries)
      if (gi >= 0) {
        // 併入既有 group,並丟棄它之後的(只會是 turn_complete)token 行,
        // 讓連續工具動作收成同一張折疊卡。
        const group = entries[gi] as Extract<FlowEntry, { kind: 'tool_group' }>
        const merged: FlowEntry = { ...group, items: [...group.items, newItem] }
        return {
          ...state,
          entries: [...entries.slice(0, gi), merged],
          liveAssistant: '',
          liveThinking: '',
        }
      }
      entries.push({ kind: 'tool_group', id: newId(), items: [newItem] })
      return { ...state, entries, liveAssistant: '', liveThinking: '' }
    }
    case 'tool_result': {
      const entries = [...state.entries]
      for (let i = entries.length - 1; i >= 0; i--) {
        const e = entries[i]
        if (!e || e.kind !== 'tool_group') continue
        const items = e.items.map((it) =>
          it.toolUseId === ev.tool_use_id
            ? {
                ...it,
                result: { content: ev.content, isError: ev.is_error ?? false },
              }
            : it,
        )
        entries[i] = { ...e, items }
        break
      }
      return { ...state, entries }
    }
    case 'turn_complete': {
      const entries = [...state.entries]
      if (state.liveAssistant.trim()) {
        entries.push({
          kind: 'assistant',
          id: newId(),
          text: state.liveAssistant,
        })
      }
      if (state.liveThinking.trim()) {
        entries.push({
          kind: 'thinking',
          id: newId(),
          text: state.liveThinking,
        })
      }
      entries.push({
        kind: 'turn_complete',
        id: newId(),
        stop_reason: ev.stop_reason,
        input_tokens: ev.input_tokens,
        output_tokens: ev.output_tokens,
      })
      return { ...state, entries, liveAssistant: '', liveThinking: '' }
    }
    case 'terminal':
      return {
        ...state,
        entries: [
          ...state.entries,
          {
            kind: 'terminal',
            id: newId(),
            reason: ev.reason,
            total_turns: ev.total_turns,
          },
        ],
        inFlight: false,
      }
    case 'error':
      return {
        ...state,
        entries: [
          ...state.entries,
          { kind: 'error', id: newId(), message: ev.message },
        ],
        inFlight: false,
      }
    case 'budget_exceeded':
      return { ...state, notice: 'budget', inFlight: false }
    case 'auto_compact_suggested':
      return { ...state, notice: 'autocompact' }
    default:
      return state
  }
}
