import { describe, expect, it } from 'vitest'
import { EMPTY, reduce, type FlowState } from './chatFlow'
import type { ServerEvent } from '../types/events'

function run(events: ServerEvent[]): FlowState {
  return events.reduce((s, e) => reduce(s, e), { ...EMPTY })
}

const tc: ServerEvent = {
  type: 'turn_complete',
  stop_reason: 'end_turn',
  input_tokens: 1,
  output_tokens: 1,
}

describe('chatFlow grouping', () => {
  it('merges consecutive tool calls across turn_complete into one group', () => {
    const s = run([
      { type: 'tool_use', tool_use_id: 'a', tool_name: 'Bash', input: {} },
      {
        type: 'tool_result',
        tool_use_id: 'a',
        tool_name: 'Bash',
        content: 'ok',
      },
      tc,
      { type: 'tool_use', tool_use_id: 'b', tool_name: 'Read', input: {} },
      {
        type: 'tool_result',
        tool_use_id: 'b',
        tool_name: 'Read',
        content: 'ok',
      },
      tc,
      { type: 'tool_use', tool_use_id: 'c', tool_name: 'Edit', input: {} },
      {
        type: 'tool_result',
        tool_use_id: 'c',
        tool_name: 'Edit',
        content: 'ok',
      },
    ])
    const groups = s.entries.filter((e) => e.kind === 'tool_group')
    expect(groups).toHaveLength(1)
    expect(
      (groups[0] as { items: { toolName: string }[] }).items.map(
        (i) => i.toolName,
      ),
    ).toEqual(['Bash', 'Read', 'Edit'])
    // 併入後,中間的 turn_complete token 行被移除
    expect(s.entries.filter((e) => e.kind === 'turn_complete')).toHaveLength(0)
    // tool_result 有填回 merged group
    const items = (groups[0] as { items: { result?: unknown }[] }).items
    expect(items.every((i) => i.result)).toBe(true)
  })

  it('assistant text breaks the group', () => {
    const s = run([
      { type: 'tool_use', tool_use_id: 'a', tool_name: 'Bash', input: {} },
      tc,
      { type: 'assistant_text', text: 'here is what I found' },
      tc,
      { type: 'tool_use', tool_use_id: 'b', tool_name: 'Read', input: {} },
    ])
    expect(s.entries.filter((e) => e.kind === 'tool_group')).toHaveLength(2)
  })
})
