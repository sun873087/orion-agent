/**
 * Tool calls 群組顯示 — 同一個 assistant turn 內的所有 tool calls 包成一個
 * 可摺疊區塊。對齊 Anthropic Claude desktop 的 UX:
 *   摺疊:`Ran 4 commands · read 2 files · created 1 file ›`
 *   展開:每筆 tool 一行精簡(`Read foo.py` / `Bash $ python3 ...`),
 *         row 再點看 raw input/output。
 */
import { useState } from 'react'
import {
  Brain,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleX,
  Code,
  Edit3,
  ExternalLink,
  Eye,
  FileText,
  Folder,
  Globe,
  ListChecks,
  Loader2,
  type LucideIcon,
  Plug,
  Search,
  Sparkles,
  Terminal,
} from 'lucide-react'

import type { ToolCallState } from '../store/agent'

type Display = {
  icon: LucideIcon
  /** 摺疊狀態這行讓 user 一眼看到「在跑什麼」。 */
  title: string
  /** 分類 key 給 summary 統計用。 */
  bucket:
    | 'read'
    | 'write'
    | 'edit'
    | 'bash'
    | 'web'
    | 'open'
    | 'skill'
    | 'task'
    | 'memory'
    | 'mcp'
    | 'other'
}

/** Tool name + input → 顯示元組。 */
function describe(toolName: string, input: Record<string, unknown> | undefined): Display {
  const i = (input ?? {}) as Record<string, unknown>
  const s = (k: string): string | undefined => {
    const v = i[k]
    return typeof v === 'string' ? v : undefined
  }
  const short = (p: string | undefined, max = 60) => {
    if (!p) return ''
    return p.length > max ? '…' + p.slice(-max) : p
  }

  switch (toolName) {
    case 'FileRead':
      return { icon: FileText, title: `Read ${short(s('file_path'))}`, bucket: 'read' }
    case 'FileWrite':
      return { icon: FileText, title: `Write ${short(s('file_path'))}`, bucket: 'write' }
    case 'FileEdit':
      return { icon: Edit3, title: `Edit ${short(s('file_path'))}`, bucket: 'edit' }
    case 'NotebookEdit':
      return { icon: Edit3, title: `Edit notebook ${short(s('notebook_path'))}`, bucket: 'edit' }
    case 'Bash': {
      const cmd = s('command') ?? ''
      return { icon: Terminal, title: `$ ${cmd.length > 80 ? cmd.slice(0, 80) + '…' : cmd}`, bucket: 'bash' }
    }
    case 'Glob':
      return { icon: Search, title: `Glob ${s('pattern') ?? ''}`, bucket: 'read' }
    case 'Grep':
      return { icon: Search, title: `Grep ${s('pattern') ?? ''}`, bucket: 'read' }
    case 'WebFetch':
      return { icon: Globe, title: `Fetch ${short(s('url'), 50)}`, bucket: 'web' }
    case 'WebSearch':
      return { icon: Search, title: `Search "${s('query') ?? ''}"`, bucket: 'web' }
    case 'open_url':
      return { icon: ExternalLink, title: `Open ${short(s('url'), 50)}`, bucket: 'open' }
    case 'open_path':
      return { icon: Folder, title: `Open ${short(s('path'))}`, bucket: 'open' }
    case 'Skill': {
      const skill = s('skill_name')
      return { icon: Sparkles, title: skill ? `Skill: ${skill}` : 'List skills', bucket: 'skill' }
    }
    case 'TodoWrite':
      return { icon: ListChecks, title: 'Update todo list', bucket: 'task' }
    case 'TaskCreate':
    case 'TaskGet':
    case 'TaskList':
    case 'TaskUpdate':
    case 'TaskStop':
    case 'TaskOutput':
      return { icon: ListChecks, title: toolName, bucket: 'task' }
    case 'EnterWorkdir':
      return { icon: Folder, title: `cd ${short(s('path'))}`, bucket: 'other' }
    case 'ExitWorkdir':
      return { icon: Folder, title: 'Exit workdir', bucket: 'other' }
    case 'AskUserQuestion':
      return { icon: Brain, title: 'Ask user', bucket: 'other' }
    case 'ConfigTool':
      return { icon: Code, title: 'Config', bucket: 'other' }
    case 'ToolSearch':
      return { icon: Search, title: 'Tool search', bucket: 'other' }
    case 'Sleep':
      return { icon: Loader2, title: `Sleep ${i['seconds'] ?? ''}s`, bucket: 'other' }
    default:
      // MCP tools: mcp__<server>__<tool>
      if (toolName.startsWith('mcp__')) {
        const parts = toolName.split('__')
        return {
          icon: Plug,
          title: `MCP: ${parts[1] ?? ''}/${parts.slice(2).join('__') ?? ''}`,
          bucket: 'mcp',
        }
      }
      return { icon: Code, title: toolName, bucket: 'other' }
  }
}

function summarize(tools: ToolCallState[]): string {
  const buckets = new Map<Display['bucket'], number>()
  for (const t of tools) {
    const b = describe(t.toolName, t.input).bucket
    buckets.set(b, (buckets.get(b) ?? 0) + 1)
  }
  const parts: string[] = []
  const label = (b: Display['bucket'], n: number): string => {
    switch (b) {
      case 'read':
        return n === 1 ? 'read 1 file' : `read ${n} files`
      case 'write':
        return n === 1 ? 'wrote 1 file' : `wrote ${n} files`
      case 'edit':
        return n === 1 ? 'edited 1 file' : `edited ${n} files`
      case 'bash':
        return n === 1 ? 'ran 1 command' : `ran ${n} commands`
      case 'web':
        return n === 1 ? '1 web request' : `${n} web requests`
      case 'open':
        return n === 1 ? 'opened 1 thing' : `opened ${n} things`
      case 'skill':
        return n === 1 ? 'used 1 skill' : `used ${n} skills`
      case 'task':
        return n === 1 ? 'updated todo list' : `${n} task ops`
      case 'memory':
        return n === 1 ? '1 memory op' : `${n} memory ops`
      case 'mcp':
        return n === 1 ? '1 MCP call' : `${n} MCP calls`
      case 'other':
        return n === 1 ? '1 tool' : `${n} tools`
    }
  }
  // 排序:bash → read → write → edit → web → skill → task → open → mcp → other
  const order: Display['bucket'][] = [
    'bash', 'read', 'write', 'edit', 'web', 'skill', 'task', 'open', 'memory', 'mcp', 'other',
  ]
  for (const b of order) {
    const n = buckets.get(b) ?? 0
    if (n > 0) parts.push(label(b, n))
  }
  return parts.join(' · ')
}

export function ToolCallGroup({ toolCalls }: { toolCalls: ToolCallState[] }) {
  const [open, setOpen] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  // 任一個 tool running → group 預設展開讓 user 看到即時 progress
  const anyRunning = toolCalls.some((t) => t.status === 'running')
  const effectiveOpen = open || anyRunning
  const anyError = toolCalls.some((t) => t.status === 'error')

  function toggleRow(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div
      className={`overflow-hidden rounded-lg border ${
        anyError ? 'border-error/30' : 'border-bg-hover'
      } bg-bg-panel`}
    >
      <button
        type="button"
        onClick={() => setOpen(!effectiveOpen)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bg-hover"
      >
        {effectiveOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {anyRunning ? (
          <Loader2 size={14} className="animate-spin text-fg-muted" />
        ) : anyError ? (
          <CircleX size={14} className="text-error" />
        ) : (
          <CircleCheck size={14} className="text-success" />
        )}
        <span className="text-xs text-fg-muted">
          {summarize(toolCalls)}
        </span>
      </button>
      {effectiveOpen && (
        <ul className="border-t border-bg-hover">
          {toolCalls.map((t) => {
            const d = describe(t.toolName, t.input)
            const Icon = d.icon
            const rowOpen = expandedIds.has(t.toolUseId)
            const isRunning = t.status === 'running'
            const isError = t.status === 'error'
            const detailText = t.text || t.progress.join('\n')
            return (
              <li
                key={t.toolUseId}
                className={`border-b border-bg-hover/60 last:border-b-0 ${
                  isError ? 'bg-error/5' : ''
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggleRow(t.toolUseId)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-bg-hover"
                >
                  {rowOpen ? <ChevronDown size={11} className="opacity-60" /> : <ChevronRight size={11} className="opacity-60" />}
                  {isRunning ? (
                    <Loader2 size={11} className="animate-spin text-fg-muted" />
                  ) : isError ? (
                    <CircleX size={11} className="text-error" />
                  ) : (
                    <Eye size={11} className="text-fg-subtle" />
                  )}
                  <Icon size={12} className="shrink-0 text-fg-muted" />
                  <span className="flex-1 truncate font-mono text-fg-base">{d.title}</span>
                </button>
                {rowOpen && (
                  <div className="bg-bg-input px-4 py-2">
                    {t.input && Object.keys(t.input).length > 0 && (
                      <pre className="scrollbar-thin mb-2 max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-fg-subtle">
                        {JSON.stringify(t.input, null, 2)}
                      </pre>
                    )}
                    {isRunning && !detailText ? (
                      <div className="text-[11px] italic text-fg-muted">running…</div>
                    ) : (
                      <pre className="scrollbar-thin max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-fg-base">
                        {detailText || '(no output)'}
                      </pre>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
