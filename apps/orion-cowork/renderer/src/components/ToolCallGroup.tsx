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

import { explainToolInput, getPermissions, sendToolApproval, setPermissions } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore, type ToolCallState } from '../store/agent'
import { useSettingsStore } from '../store/settings'

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

/** 拿 path 的 basename(不依賴 path module — renderer 沒 node 環境)。 */
function basename(p: string): string {
  if (!p) return ''
  const norm = p.replace(/\\/g, '/').replace(/\/+$/, '')
  const idx = norm.lastIndexOf('/')
  return idx >= 0 ? norm.slice(idx + 1) : norm
}

/** 從 URL 抽 hostname,失敗就回原字串。 */
function hostFromUrl(u: string): string {
  try {
    return new URL(u).hostname || u
  } catch {
    return u
  }
}

/**
 * 把 tool name + input 翻成自然語言動詞片語,給 ApprovalBanner 用。
 * 非工程使用者也看得懂。回 null 表示沒對應翻譯,banner 退回舊「tool: pattern」格式。
 */
function humanAction(
  toolName: string,
  input: Record<string, unknown> | undefined,
  t: (key: string, params?: Record<string, string | number>) => string,
): string | null {
  const i = (input ?? {}) as Record<string, unknown>
  const s = (k: string): string => (typeof i[k] === 'string' ? (i[k] as string) : '')
  switch (toolName) {
    case 'Read': {
      const p = s('path')
      return p ? t('approval.action.read', { name: basename(p) }) : null
    }
    case 'Write': {
      const p = s('path')
      return p ? t('approval.action.write', { name: basename(p) }) : null
    }
    case 'Edit': {
      const p = s('path')
      return p ? t('approval.action.edit', { name: basename(p) }) : null
    }
    case 'NotebookEdit': {
      const p = s('notebook_path') || s('path')
      return p ? t('approval.action.notebookEdit', { name: basename(p) }) : null
    }
    case 'Bash':
      return t('approval.action.bash')
    case 'Glob': {
      const p = s('pattern')
      if (!p) return null
      return p === '*' || p === '**/*'
        ? t('approval.action.globAll')
        : t('approval.action.glob', { pattern: p })
    }
    case 'Grep': {
      const p = s('pattern')
      return p ? t('approval.action.grep', { pattern: p }) : null
    }
    case 'WebFetch': {
      const u = s('url')
      return u ? t('approval.action.webFetch', { host: hostFromUrl(u) }) : null
    }
    case 'WebSearch': {
      const q = s('query')
      return q ? t('approval.action.webSearch', { query: q }) : null
    }
    case 'open_url': {
      const u = s('url')
      return u ? t('approval.action.openUrl', { host: hostFromUrl(u) }) : null
    }
    case 'open_path': {
      const p = s('path')
      return p ? t('approval.action.openPath', { name: basename(p) }) : null
    }
    case 'TodoWrite':
      return t('approval.action.todoWrite')
    case 'AskUserQuestion':
      return t('approval.action.askUserQuestion')
    default:
      return null
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
  const { t, locale } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const [explainState, setExplainState] = useState<
    | { status: 'idle' }
    | { status: 'loading' }
    | { status: 'done'; text: string }
    | { status: 'error'; message: string }
  >({ status: 'idle' })
  const summaryProvider = useSettingsStore((s) => s.compactSummaryProvider)
  const summaryModel = useSettingsStore((s) => s.compactSummaryModel)
  const d = describe(toolName, input)
  const action = humanAction(toolName, input, t)
  const summary = humanSummary(toolName, input)
  const allowPattern = suggestAllowPattern(toolName, input)

  async function handleExplain() {
    if (explainState.status === 'loading') return
    setExplainState({ status: 'loading' })
    try {
      const text = await explainToolInput({
        toolName,
        toolInput: input ?? {},
        summaryProvider,
        summaryModel,
        locale,
      })
      setExplainState({ status: 'done', text })
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      setExplainState({ status: 'error', message })
    }
  }
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
        <span>
          {action
            ? t('approval.banner.titleAction', { action })
            : t('approval.banner.title', { tool: d.title })}
        </span>
      </div>
      {summary && (
        <pre className="scrollbar-thin mb-2 max-h-24 overflow-auto whitespace-pre-wrap rounded-md bg-bg-base/60 px-2 py-1.5 font-mono text-[11px] text-fg-base">
          {summary}
        </pre>
      )}
      {explainState.status === 'done' && (
        <div className="mb-2 flex items-start gap-1.5 rounded-md bg-info/10 px-2 py-1.5 text-[11px] text-fg-base">
          <Sparkles size={12} className="mt-0.5 shrink-0 text-info" />
          <span>{explainState.text}</span>
        </div>
      )}
      {explainState.status === 'error' && (
        <div className="mb-2 text-[10px] text-danger">
          {t('approval.banner.explainError', { message: explainState.message })}
        </div>
      )}
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {explainState.status !== 'done' && (
          <button
            type="button"
            onClick={handleExplain}
            disabled={explainState.status === 'loading'}
            className="flex items-center gap-1 text-[10px] text-fg-subtle hover:text-fg-muted disabled:opacity-50"
          >
            <Sparkles size={10} />
            {explainState.status === 'loading'
              ? t('approval.banner.explainLoading')
              : t('approval.banner.explain')}
          </button>
        )}
        {rawJson && (
          <button
            type="button"
            onClick={() => setShowRaw((v) => !v)}
            className="text-[10px] text-fg-subtle hover:text-fg-muted"
          >
            {showRaw ? t('approval.banner.hideRaw') : t('approval.banner.viewRaw')}
          </button>
        )}
      </div>
      {rawJson && showRaw && (
        <pre className="scrollbar-thin mb-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-bg-base/60 px-2 py-1.5 font-mono text-[10px] text-fg-muted">
          {rawJson}
        </pre>
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

/**
 * 在 tool error row 展開區塊內提供「✨ 看不懂這個錯誤?讓 AI 解釋」按鈕。
 * 點下去 call tool.explain RPC 帶上 error_text,sidecar 用 Settings 的「摘要
 * model」生 2-3 句人話。沒設摘要 model 或 LLM 失敗 → 顯紅色小字,可重試。
 *
 * Component state(idle/loading/done/error)綁在 row 上 — row collapse 時整個
 * component unmount,結果 cache 不跨 collapse 保留(同 row 多次展開要重點)。
 * 想跨 collapse cache 之後可以拉到 ToolCallGroup 層級。
 */
function ToolErrorExplain({
  toolName,
  input,
  errorText,
}: {
  toolName: string
  input: Record<string, unknown> | undefined
  errorText: string
}) {
  const { t, locale } = useTranslation()
  const [state, setState] = useState<
    | { status: 'idle' }
    | { status: 'loading' }
    | { status: 'done'; text: string }
    | { status: 'error'; message: string }
  >({ status: 'idle' })
  const summaryProvider = useSettingsStore((s) => s.compactSummaryProvider)
  const summaryModel = useSettingsStore((s) => s.compactSummaryModel)

  async function handleExplain() {
    if (state.status === 'loading') return
    setState({ status: 'loading' })
    try {
      const text = await explainToolInput({
        toolName,
        toolInput: input ?? {},
        summaryProvider,
        summaryModel,
        locale,
        errorText,
      })
      setState({ status: 'done', text })
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      setState({ status: 'error', message })
    }
  }

  return (
    <div className="mb-2">
      {state.status === 'done' && (
        <div className="mb-1.5 flex items-start gap-1.5 rounded-md bg-info/10 px-2 py-1.5 text-[11px] text-fg-base">
          <Sparkles size={12} className="mt-0.5 shrink-0 text-info" />
          <span className="whitespace-pre-wrap">{state.text}</span>
        </div>
      )}
      {state.status === 'error' && (
        <div className="mb-1 text-[10px] text-danger">
          {t('tool.error.explainError', { message: state.message })}
        </div>
      )}
      {state.status !== 'done' && (
        <button
          type="button"
          onClick={handleExplain}
          disabled={state.status === 'loading'}
          className="flex items-center gap-1 rounded text-[10px] text-fg-subtle hover:text-fg-muted disabled:opacity-50"
        >
          <Sparkles size={10} />
          {state.status === 'loading'
            ? t('tool.error.explainLoading')
            : t('tool.error.explain')}
        </button>
      )}
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
                    {isError && detailText && (
                      <ToolErrorExplain
                        toolName={t.toolName}
                        input={t.input}
                        errorText={detailText}
                      />
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
