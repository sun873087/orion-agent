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
  Check,
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
  Hand,
  ListChecks,
  Loader2,
  type LucideIcon,
  Plug,
  Search,
  Sparkles,
  Terminal,
  X,
} from 'lucide-react'

import { getPermissions, sendToolApproval, setPermissions } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore, type ToolCallState } from '../store/agent'
import { DiffViewer } from './DiffViewer'

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
    case 'Read':
      return { icon: FileText, title: `Read ${short(s('path'))}`, bucket: 'read' }
    case 'Write':
      return { icon: FileText, title: `Write ${short(s('path'))}`, bucket: 'write' }
    case 'Edit':
      return { icon: Edit3, title: `Edit ${short(s('path'))}`, bucket: 'edit' }
    case 'NotebookEdit':
      return {
        icon: Edit3,
        title: `Edit notebook ${short(s('notebook_path') ?? s('path'))}`,
        bucket: 'edit',
      }
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

/**
 * 給「永遠允許」按鈕用的 pattern 建議 — 對熟知 tool 給更精準的 glob。
 * Bash:抓前兩 token 配 *,WebFetch:抓 hostname。其他就回 tool name 全允許。
 */
function suggestAllowPattern(toolName: string, input: Record<string, unknown> | undefined): string {
  const i = (input ?? {}) as Record<string, unknown>
  const s = (k: string) => (typeof i[k] === 'string' ? (i[k] as string) : '')
  switch (toolName) {
    case 'Bash': {
      const cmd = s('command').trim()
      if (!cmd) return 'Bash'
      const tokens = cmd.split(/\s+/).filter(Boolean)
      // 一個 token 就 `Bash(tok *)`(吃所有 sub-args);兩個就前兩 token + *
      const head = tokens.length >= 2 ? tokens.slice(0, 2).join(' ') : tokens[0]
      return `Bash(${head} *)`
    }
    case 'WebFetch': {
      const url = s('url')
      try {
        const u = new URL(url)
        if (u.hostname) return `WebFetch(domain:${u.hostname})`
      } catch {
        // ignore — fall through
      }
      return 'WebFetch'
    }
    default:
      return toolName
  }
}

/**
 * 對重點 tool 給「人話」摘要(banner 上方一行讓 user 一眼看懂在做什麼)。
 * 不在這 switch 內的 tool fallback 顯 describe() title。
 */
function humanSummary(toolName: string, input: Record<string, unknown> | undefined): string | null {
  const i = (input ?? {}) as Record<string, unknown>
  const s = (k: string): string => (typeof i[k] === 'string' ? (i[k] as string) : '')
  switch (toolName) {
    case 'Bash':
      return s('command') || null
    case 'Read':
    case 'Write':
    case 'Edit':
      return s('path') || null
    case 'NotebookEdit':
      return s('notebook_path') || s('path') || null
    case 'Glob':
    case 'Grep':
      return s('pattern') || null
    case 'WebFetch':
    case 'open_url':
      return s('url') || null
    case 'WebSearch':
      return s('query') || null
    case 'open_path':
      return s('path') || null
    default:
      return null
  }
}

/** Ask 模式下 — 工具在等使用者按 Approve / Deny。 */
function ToolApprovalBanner({
  toolUseId,
  toolName,
  input,
}: {
  toolUseId: string
  toolName: string
  input: Record<string, unknown> | undefined
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const d = describe(toolName, input)
  const summary = humanSummary(toolName, input)
  const allowPattern = suggestAllowPattern(toolName, input)
  const rawJson =
    input && Object.keys(input).length > 0
      ? JSON.stringify(input, null, 2)
      : ''

  async function decide(decision: 'allow' | 'deny') {
    if (busy) return
    setBusy(true)
    // Optimistic UI:立刻把 banner 從 awaiting_approval 拉回 running,user
    // 不用等 RPC + tool 跑完才看到 banner 消失。後續 tool_result 來會 finalize
    // 成 success / error。
    {
      const sid = useAgentStore.getState().sessionId
      if (sid) useAgentStore.getState().clearToolApprovalUI(sid, toolUseId)
    }
    try {
      await sendToolApproval(toolUseId, decision)
    } finally {
      setBusy(false)
    }
  }

  /** 「永遠允許」:把 pattern 加進 global allow,然後 approve 這次 call。 */
  async function alwaysAllow() {
    if (busy) return
    setBusy(true)
    {
      const sid = useAgentStore.getState().sessionId
      if (sid) useAgentStore.getState().clearToolApprovalUI(sid, toolUseId)
    }
    try {
      const cur = await getPermissions('global')
      // 已在 allow list 就不重複加
      const allow = cur.allow.includes(allowPattern)
        ? cur.allow
        : [...cur.allow, allowPattern]
      await setPermissions('global', allow, cur.deny)
      await sendToolApproval(toolUseId, 'allow')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-y border-warning/30 bg-warning/5 px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-xs text-warning">
        <Hand size={12} />
        <span>{t('approval.banner.title', { tool: d.title })}</span>
      </div>
      {summary && (
        <pre className="scrollbar-thin mb-2 max-h-24 overflow-auto whitespace-pre-wrap rounded-md bg-bg-base/60 px-2 py-1.5 font-mono text-[11px] text-fg-base">
          {summary}
        </pre>
      )}
      {rawJson && (
        <div className="mb-2">
          <button
            type="button"
            onClick={() => setShowRaw((v) => !v)}
            className="text-[10px] text-fg-subtle hover:text-fg-muted"
          >
            {showRaw ? t('approval.banner.hideRaw') : t('approval.banner.viewRaw')}
          </button>
          {showRaw && (
            <pre className="scrollbar-thin mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-bg-base/60 px-2 py-1.5 font-mono text-[10px] text-fg-muted">
              {rawJson}
            </pre>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => decide('allow')}
          disabled={busy}
          className="flex items-center gap-1 rounded-md bg-success/20 px-3 py-1 text-xs font-medium text-success hover:bg-success/30 disabled:opacity-40"
        >
          <Check size={12} />
          <span>{t('approval.allow')}</span>
        </button>
        <button
          type="button"
          onClick={alwaysAllow}
          disabled={busy}
          title={t('approval.alwaysAllow.tooltip', { pattern: allowPattern })}
          className="flex items-center gap-1 rounded-md bg-success/10 px-3 py-1 text-xs font-medium text-success/90 hover:bg-success/20 disabled:opacity-40"
        >
          <Check size={12} />
          <span>
            {t('approval.alwaysAllow')}{' '}
            <code className="font-mono text-[10px] opacity-80">{allowPattern}</code>
          </span>
        </button>
        <button
          type="button"
          onClick={() => decide('deny')}
          disabled={busy}
          className="flex items-center gap-1 rounded-md bg-error/20 px-3 py-1 text-xs font-medium text-error hover:bg-error/30 disabled:opacity-40"
        >
          <X size={12} />
          <span>{t('approval.deny')}</span>
        </button>
      </div>
    </div>
  )
}

export function ToolCallGroup({ toolCalls }: { toolCalls: ToolCallState[] }) {
  const [open, setOpen] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  // 任一個 tool running 或 awaiting_approval → group 預設展開,讓 user 看
  // 到即時 progress / approval banner。
  const anyRunning = toolCalls.some(
    (t) => t.status === 'running' || t.status === 'awaiting_approval',
  )
  const effectiveOpen = open || anyRunning
  // 中間錯誤常見(model 試錯再 fix-forward),不該污染整個 group。
  // 只看最後一個 tool 的狀態 = turn 的 final outcome。
  const lastTool = toolCalls[toolCalls.length - 1]
  const groupErrored = lastTool?.status === 'error'

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
        groupErrored ? 'border-error/30' : 'border-bg-hover'
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
        ) : groupErrored ? (
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
            const isAwaiting = t.status === 'awaiting_approval'
            const detailText = t.text || t.progress.join('\n')
            return (
              <li
                key={t.toolUseId}
                className={`border-b border-bg-hover/60 last:border-b-0 ${
                  isError ? 'bg-error/5' : isAwaiting ? 'bg-warning/5' : ''
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggleRow(t.toolUseId)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-bg-hover"
                >
                  {rowOpen ? <ChevronDown size={11} className="opacity-60" /> : <ChevronRight size={11} className="opacity-60" />}
                  {isAwaiting ? (
                    <Hand size={11} className="text-warning" />
                  ) : isRunning ? (
                    <Loader2 size={11} className="animate-spin text-fg-muted" />
                  ) : isError ? (
                    <CircleX size={11} className="text-error" />
                  ) : (
                    <Eye size={11} className="text-fg-subtle" />
                  )}
                  <Icon size={12} className="shrink-0 text-fg-muted" />
                  <span className="flex-1 truncate font-mono text-fg-base">{d.title}</span>
                </button>
                {isAwaiting && (
                  <ToolApprovalBanner
                    toolUseId={t.toolUseId}
                    toolName={t.toolName}
                    input={t.input}
                  />
                )}
                {rowOpen && (
                  <div className="bg-bg-input px-4 py-2">
                    {t.input && Object.keys(t.input).length > 0 && (
                      <pre className="scrollbar-thin mb-2 max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-fg-subtle">
                        {JSON.stringify(t.input, null, 2)}
                      </pre>
                    )}
                    {/* Phase 31-V — Edit/Write/NotebookEdit 顯實際 unified diff */}
                    {t.editSnapshot && (
                      <DiffViewer snapshot={t.editSnapshot} />
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
