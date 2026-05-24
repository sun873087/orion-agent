import { describe, expect, it } from 'vitest'
import { deriveDetail } from './detailPanel'
import type { ServerEvent } from '../types/events'

describe('deriveDetail', () => {
  it('extracts latest todos and unique skills from tool_use events', () => {
    const events: ServerEvent[] = [
      {
        type: 'tool_use',
        tool_use_id: '1',
        tool_name: 'Skill',
        input: { name: 'code-review' },
      },
      {
        type: 'tool_use',
        tool_use_id: '2',
        tool_name: 'TodoWrite',
        input: {
          todos: [
            { content: 'step a', status: 'completed' },
            { content: 'step b', status: 'in_progress' },
          ],
        },
      },
      {
        type: 'tool_use',
        tool_use_id: '3',
        tool_name: 'Skill',
        input: { name: 'code-review' }, // dup → 去重
      },
    ]
    const { todos, skills } = deriveDetail(events)
    expect(todos).toHaveLength(2)
    expect(todos[0]).toEqual({ content: 'step a', status: 'completed' })
    expect(skills).toEqual(['code-review'])
  })

  it('returns empty when no relevant events', () => {
    const { todos, skills } = deriveDetail([
      { type: 'assistant_text', text: 'hi' },
    ])
    expect(todos).toEqual([])
    expect(skills).toEqual([])
  })
})
