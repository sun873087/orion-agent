import type { ServerEvent } from '../types/events'

export interface TodoItem {
  content: string
  status: string
}

export interface DetailData {
  todos: TodoItem[]
  skills: string[]
}

/**
 * 從 WS 事件流推導 right panel 的內容(無需後端):
 * - todos:最後一次 TodoWrite tool_use 的 input.todos
 * - skills:所有 Skill tool_use 用過的 skill 名(去重、保序)
 */
export function deriveDetail(events: ServerEvent[]): DetailData {
  let todos: TodoItem[] = []
  const skills: string[] = []
  for (const ev of events) {
    if (ev.type !== 'tool_use') continue
    if (ev.tool_name === 'TodoWrite') {
      const raw = (ev.input as { todos?: unknown }).todos
      if (Array.isArray(raw)) {
        todos = raw
          .map((t) => {
            const o = t as { content?: unknown; status?: unknown }
            return {
              content: typeof o.content === 'string' ? o.content : '',
              status: typeof o.status === 'string' ? o.status : 'pending',
            }
          })
          .filter((t) => t.content)
      }
    } else if (ev.tool_name === 'Skill') {
      const name = (ev.input as { name?: unknown }).name
      if (typeof name === 'string' && !skills.includes(name)) skills.push(name)
    }
  }
  return { todos, skills }
}
