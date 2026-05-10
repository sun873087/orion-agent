/**
 * Tool 顯示文字 / chip / summary 邏輯,集中於此純函式 module。
 *
 * - describeToolItem(): 一行人話描述,如 "Read foo.py"、"Ran command (model description)"
 * - toolTypeChip(): 右側類型標籤,如 "Script" / "Read" / "Search"
 * - formatGroupSummary(): 把多個 tool 概括成 "Ran 2 commands, viewed 1 file"
 */

import { summarizeToolInput } from './toolSummary'

export interface ToolGroupItem {
  toolUseId: string
  toolName: string
  input: Record<string, unknown>
  result?: { content: string; isError: boolean }
}

function basenameOrFile(
  toolName: string,
  input: Record<string, unknown>,
): string {
  return summarizeToolInput(toolName, input) ?? 'file'
}

export function describeToolItem(item: ToolGroupItem): string {
  // Bash 優先用模型 narrate 的 description
  if (
    item.toolName === 'Bash' &&
    typeof item.input['description'] === 'string' &&
    item.input['description'].trim()
  ) {
    return item.input['description'].trim()
  }

  switch (item.toolName) {
    case 'Bash':
      return 'Ran command'
    case 'Read':
      return `Read ${basenameOrFile('Read', item.input)}`
    case 'Write':
      return `Wrote ${basenameOrFile('Write', item.input)}`
    case 'Edit':
      return `Edited ${basenameOrFile('Edit', item.input)}`
    case 'NotebookEdit':
      return `Edited notebook ${basenameOrFile('NotebookEdit', item.input)}`
    case 'Glob': {
      const p = summarizeToolInput('Glob', item.input)
      return p ? `Searched ${p}` : 'Searched files'
    }
    case 'Grep': {
      const p = summarizeToolInput('Grep', item.input)
      return p ? `Searched ${p}` : 'Searched content'
    }
    case 'WebFetch': {
      const host = summarizeToolInput('WebFetch', item.input)
      return host ? `Fetched ${host}` : 'Fetched URL'
    }
    case 'Skill': {
      const name = summarizeToolInput('Skill', item.input)
      return name ? `Used skill ${name}` : 'Used skill'
    }
    case 'TodoWrite':
      return 'Updated todos'
    case 'Agent':
      return 'Launched sub-agent'
    case 'TaskCreate':
      return 'Created task'
    case 'TaskUpdate':
      return 'Updated task'
    default:
      return `Used ${item.toolName}`
  }
}

export function toolTypeChip(toolName: string): string {
  switch (toolName) {
    case 'Bash':
      return 'Script'
    case 'Read':
      return 'Read'
    case 'Write':
    case 'Edit':
    case 'NotebookEdit':
      return 'Write'
    case 'Glob':
    case 'Grep':
      return 'Search'
    case 'WebFetch':
      return 'Fetch'
    case 'Skill':
      return 'Skill'
    case 'TodoWrite':
    case 'TaskCreate':
    case 'TaskUpdate':
      return 'Todo'
    case 'Agent':
      return 'Agent'
    default:
      return toolName
  }
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`
}

export function formatGroupSummary(items: ToolGroupItem[]): string {
  const buckets = {
    command: 0,
    viewed: 0,
    wrote: 0,
    edited: 0,
    searched: 0,
    fetched: 0,
    other: 0,
  }
  for (const it of items) {
    switch (it.toolName) {
      case 'Bash':
        buckets.command++
        break
      case 'Read':
        buckets.viewed++
        break
      case 'Write':
      case 'NotebookEdit':
        buckets.wrote++
        break
      case 'Edit':
        buckets.edited++
        break
      case 'Glob':
      case 'Grep':
        buckets.searched++
        break
      case 'WebFetch':
        buckets.fetched++
        break
      default:
        buckets.other++
        break
    }
  }
  const parts: string[] = []
  if (buckets.command)
    parts.push(`Ran ${buckets.command} ${plural(buckets.command, 'command')}`)
  if (buckets.viewed)
    parts.push(`viewed ${buckets.viewed} ${plural(buckets.viewed, 'file')}`)
  if (buckets.wrote)
    parts.push(`wrote ${buckets.wrote} ${plural(buckets.wrote, 'file')}`)
  if (buckets.edited)
    parts.push(`edited ${buckets.edited} ${plural(buckets.edited, 'file')}`)
  if (buckets.searched)
    parts.push(
      `searched ${buckets.searched} ${plural(buckets.searched, 'time')}`,
    )
  if (buckets.fetched)
    parts.push(
      `fetched ${buckets.fetched} URL${buckets.fetched > 1 ? 's' : ''}`,
    )
  if (buckets.other)
    parts.push(
      `used ${buckets.other} other tool${buckets.other > 1 ? 's' : ''}`,
    )
  if (parts.length === 0) return 'No tools'
  // capitalize first letter of result（後面段是 lowercase 銜接逗號 OK）
  const joined = parts.join(', ')
  return joined.charAt(0).toUpperCase() + joined.slice(1)
}
