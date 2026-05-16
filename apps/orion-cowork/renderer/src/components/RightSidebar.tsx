/**
 * 右側 detail panel — 對齊 Anthropic Claude Cowork 的 UX:
 *   - Progress:當前對話的 todo list(從 TodoWrite tool call input parse)
 *   - Working folder:對話內 model 寫 / 改過的檔案(FileWrite / FileEdit /
 *     NotebookEdit / open_path)
 *   - Context · Skills:對話內用過的 skill 名(從 Skill tool input)
 *
 * 所有資料源都從 useAgentStore.messages 內的 toolCalls 抽取。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2,
  Circle,
  Coins,
  ExternalLink,
  FileText,
  Folder,
  Loader2,
  Sparkles,
} from 'lucide-react'

import { getConversationStats, type ConversationStats } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'

type Todo = { content: string; status: 'pending' | 'in_progress' | 'completed' }

function extractTodos(toolCalls: Array<{ toolName: string; input?: Record<string, unknown> }>): Todo[] {
  // 取最後一次 TodoWrite 的 input.todos 當當前狀態(每次 LLM 寫 todo 都會覆蓋整 list)
  for (let i = toolCalls.length - 1; i >= 0; i--) {
    const tc = toolCalls[i]
    if (tc.toolName === 'TodoWrite' && tc.input) {
      const raw = (tc.input as { todos?: unknown }).todos
      if (Array.isArray(raw)) {
        return raw
          .filter((t): t is Todo => typeof t === 'object' && t !== null)
          .map((t) => ({
            content: String((t as Todo).content ?? ''),
            status: ((t as Todo).status ?? 'pending') as Todo['status'],
          }))
      }
    }
  }
  return []
}

type WorkingFile = { path: string; action: 'wrote' | 'edited' | 'opened' }

/** 腳本 / 中間檔 — model 寫來執行的,不算「結果產物」。 */
const SCRIPT_EXTS = new Set([
  '.py', '.pyc', '.ipynb',
  '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
  '.sh', '.bash', '.zsh', '.fish',
  '.rb', '.go', '.rs', '.java', '.kt', '.swift',
  '.cpp', '.c', '.h', '.hpp', '.cc', '.cs',
  '.lua', '.pl', '.php',
])

/** 「結果產物」副檔名白名單 — 從 message 文字內抽 path 時用。 */
const OUTPUT_EXTS = new Set([
  '.pdf', '.pptx', '.ppt', '.docx', '.doc', '.xlsx', '.xls', '.csv', '.tsv',
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.tiff',
  '.mp4', '.mov', '.mkv', '.webm', '.mp3', '.wav', '.ogg', '.flac',
  '.zip', '.tar', '.gz', '.tgz', '.7z', '.rar',
  '.html', '.htm', '.md', '.txt', '.json', '.yaml', '.yml', '.xml',
  '.epub', '.psd', '.ai', '.sketch', '.fig',
])

function isScriptFile(path: string): boolean {
  const dot = path.lastIndexOf('.')
  if (dot < 0) return false
  return SCRIPT_EXTS.has(path.slice(dot).toLowerCase())
}

function isOutputFile(path: string): boolean {
  const dot = path.lastIndexOf('.')
  if (dot < 0) return false
  return OUTPUT_EXTS.has(path.slice(dot).toLowerCase())
}

/** 從文字內掃絕對 path,只留結果產物(白名單副檔名)。 */
function outputPathsFromText(text: string): string[] {
  if (!text) return []
  // 匹配 / 開頭、空白 / 中文字 / 引號 / 換行為界、含一個 . 的 path
  const matches = text.matchAll(/(\/[^\s"'<>()`,;]+\.[a-zA-Z0-9]+)/g)
  const out = new Set<string>()
  for (const m of matches) {
    const p = m[1]
    if (isOutputFile(p)) out.add(p)
  }
  return Array.from(out)
}

/** Fallback:從 tool result text 推 file path(舊 sidecar 沒 emit tool_start 時用)。 */
function pathFromText(text: string): string | null {
  if (!text) return null
  const m =
    text.match(/(?:wrote|edited|created|overwrote)\s+(?:\d+\s+bytes\s+to\s+)?(\/\S+)/i) ??
    text.match(/(\/\S+\.\w+)/)
  return m ? m[1] : null
}

function extractWorkingFiles(
  toolCalls: Array<{ toolName: string; input?: Record<string, unknown>; status: string; text?: string }>,
): WorkingFile[] {
  // 對每個 file path 留最後一次 action;優先序:opened > wrote > edited
  // (opened = model 給 user 看的結果產物,優先顯)
  const rank: Record<WorkingFile['action'], number> = { opened: 3, wrote: 2, edited: 1 }
  const map = new Map<string, WorkingFile>()
  for (const tc of toolCalls) {
    if (tc.status === 'error') continue
    const i = tc.input ?? {}
    let p: string | undefined
    let action: WorkingFile['action'] | undefined
    if (tc.toolName === 'open_path') {
      // model 開啟給 user 看的檔 = 結果產物
      p = typeof i.path === 'string' ? i.path : undefined
      action = 'opened'
    } else if (tc.toolName === 'Write') {
      p = (typeof i.path === 'string' ? i.path : undefined)
        ?? (pathFromText(tc.text ?? '') ?? undefined)
      action = 'wrote'
    } else if (tc.toolName === 'Edit') {
      p = (typeof i.path === 'string' ? i.path : undefined)
        ?? (pathFromText(tc.text ?? '') ?? undefined)
      action = 'edited'
    } else if (tc.toolName === 'NotebookEdit') {
      p = (typeof i.notebook_path === 'string' ? i.notebook_path : undefined)
        ?? (typeof i.path === 'string' ? i.path : undefined)
        ?? (pathFromText(tc.text ?? '') ?? undefined)
      action = 'edited'
    }
    if (!p || !action) continue
    // 過濾腳本檔(Write/Edit 寫的中間檔,只有 open_path 才不過濾 — 因為 user
    // 確實有時想看開過的程式碼)
    if (action !== 'opened' && isScriptFile(p)) continue
    const prev = map.get(p)
    if (!prev || rank[action] > rank[prev.action]) {
      map.set(p, { path: p, action })
    }
  }
  return Array.from(map.values())
}

function extractSkills(toolCalls: Array<{ toolName: string; input?: Record<string, unknown> }>): string[] {
  const set = new Set<string>()
  for (const tc of toolCalls) {
    if (tc.toolName !== 'Skill') continue
    const skill = (tc.input as { skill_name?: unknown } | undefined)?.skill_name
    if (typeof skill === 'string' && skill) set.add(skill)
  }
  return Array.from(set)
}

export function RightSidebar() {
  const { t } = useTranslation()
  const messages = useAgentStore((s) => s.messages)

  // 把所有 assistant message 的 toolCalls 全攤平,給三個 extractor 用
  const allCalls = useMemo(() => {
    const out: Array<{
      toolName: string
      input?: Record<string, unknown>
      status: string
      text?: string
    }> = []
    for (const m of messages) {
      if (m.role !== 'assistant') continue
      for (const tc of m.toolCalls ?? []) {
        out.push({
          toolName: tc.toolName,
          input: tc.input,
          status: tc.status,
          text: tc.text,
        })
      }
    }
    return out
  }, [messages])

  const allAssistantText = useMemo(
    () => messages.filter((m) => m.role === 'assistant').map((m) => m.text).join('\n\n'),
    [messages],
  )

  const todos = useMemo(() => extractTodos(allCalls), [allCalls])
  const workingFiles = useMemo(() => {
    // 工作資料夾:只顯結果產物 — wrote/edited 過濾 script;再補上 text 內的 output paths
    const fromTools = extractWorkingFiles(allCalls).filter(
      (f) => f.action === 'opened' || isOutputFile(f.path),
    )
    const seen = new Set(fromTools.map((f) => f.path))
    for (const p of outputPathsFromText(allAssistantText)) {
      if (!seen.has(p)) {
        fromTools.push({ path: p, action: 'opened' })
        seen.add(p)
      }
    }
    return fromTools
  }, [allCalls, allAssistantText])
  const skills = useMemo(() => extractSkills(allCalls), [allCalls])

  return (
    <aside
      className={
        // 小視窗:fixed overlay,從 Header 底下(top-11 = h-11)拉到視窗底,
        // 避免蓋到 toolbar。 z-30 浮在 chat area 上,陰影區隔
        // ≥lg(1024px):relative 變 flex item,跟 chat area 並排
        'scrollbar-thin flex w-72 shrink-0 flex-col gap-3 overflow-y-auto border-l border-bg-hover bg-bg-panel px-3 py-3 ' +
        'fixed bottom-0 right-0 top-11 z-30 shadow-2xl ' +
        'lg:relative lg:top-auto lg:bottom-auto lg:z-auto lg:shadow-none'
      }
    >
      <Section title={t('rightSidebar.progress')}>
        {todos.length === 0 ? (
          <Empty>{t('rightSidebar.noProgress')}</Empty>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {todos.map((todo, i) => (
              <li key={i} className="flex items-start gap-2">
                {todo.status === 'completed' ? (
                  <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-success" />
                ) : todo.status === 'in_progress' ? (
                  <Loader2 size={12} className="mt-0.5 shrink-0 animate-spin text-accent" />
                ) : (
                  <Circle size={12} className="mt-0.5 shrink-0 text-fg-subtle" />
                )}
                <span
                  className={`text-xs ${
                    todo.status === 'completed'
                      ? 'text-fg-subtle line-through'
                      : 'text-fg-base'
                  }`}
                >
                  {todo.content}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t('rightSidebar.workingFolder')}>
        {workingFiles.length === 0 ? (
          <Empty>{t('rightSidebar.noFiles')}</Empty>
        ) : (
          <ul className="flex flex-col gap-1">
            {workingFiles.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  onClick={() => window.shellApi.openPath(f.path)}
                  title={f.path}
                  className="flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left hover:bg-bg-hover"
                >
                  <FileText size={12} className="mt-0.5 shrink-0 text-fg-muted" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-fg-base">
                      {f.path.split('/').pop()}
                    </div>
                    <div className="truncate font-mono text-[10px] text-fg-subtle">
                      {f.path}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      window.shellApi.revealInFinder(f.path)
                    }}
                    title={t('rightSidebar.revealInFinder')}
                    className="opacity-60 hover:opacity-100"
                  >
                    <Folder size={11} />
                  </button>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t('rightSidebar.context')}>
        {skills.length === 0 ? (
          <Empty>{t('rightSidebar.noSkills')}</Empty>
        ) : (
          <>
            <div className="mb-1 text-[10px] uppercase tracking-wide text-fg-subtle">
              {t('rightSidebar.skills')}
            </div>
            <ul className="flex flex-wrap gap-1">
              {skills.map((s) => (
                <li
                  key={s}
                  className="flex items-center gap-1 rounded-md bg-bg-hover px-2 py-0.5 text-[11px]"
                >
                  <Sparkles size={10} className="text-accent" />
                  <span className="font-mono text-fg-base">{s}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      <UsageSection />
    </aside>
  )
}

/**
 * Cost / context / cache 使用量區塊。
 *
 * 拉 sidecar `conversation.stats` RPC,在以下時機 refresh:
 *   - sessionId 變更(切對話)
 *   - busy 轉 false(turn 剛結束,stats 才會更新)
 *
 * 顯三層:
 *   - 本次對話(last turn)— input / output / cache_read / cost
 *   - 整個 session 累積 — tokens + cost
 *   - Context window — used / max + cache hit rate
 */
function UsageSection() {
  const { t } = useTranslation()
  const sessionId = useAgentStore((s) => s.sessionId)
  const busy = useAgentStore((s) => s.busy)
  const [stats, setStats] = useState<ConversationStats | null>(null)
  const [loading, setLoading] = useState(false)

  // 換 session 馬上清舊資料,避免閃前面 session 的數字
  useEffect(() => {
    setStats(null)
  }, [sessionId])

  // sessionId 有 + busy 轉 false(turn 結束)時 refetch
  useEffect(() => {
    if (!sessionId || busy) return
    let cancelled = false
    setLoading(true)
    getConversationStats(sessionId)
      .then((s) => {
        if (!cancelled) setStats(s)
      })
      .catch(() => {
        if (!cancelled) setStats(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [sessionId, busy])

  if (!sessionId) {
    return (
      <Section title={t('rightSidebar.usage')}>
        <Empty>{t('rightSidebar.noUsage')}</Empty>
      </Section>
    )
  }

  if (!stats || stats.turns === 0) {
    return (
      <Section title={t('rightSidebar.usage')}>
        <Empty>
          {loading ? t('rightSidebar.loadingUsage') : t('rightSidebar.noUsage')}
        </Empty>
      </Section>
    )
  }

  const contextPct = stats.contextMax > 0 ? (stats.contextUsed / stats.contextMax) * 100 : 0
  const cacheHitPct = stats.cacheHitRate * 100

  return (
    <Section title={t('rightSidebar.usage')}>
      <div className="flex flex-col gap-3 text-xs">
        {/* 本次對話 (last turn) */}
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-fg-subtle">
            <span>{t('rightSidebar.lastTurn')}</span>
          </div>
          <UsageRow
            label={t('rightSidebar.cost')}
            value={`$${stats.lastTurn.costUsd.toFixed(4)}`}
            highlight
          />
          <UsageRow label="input" value={fmt(stats.lastTurn.inputTokens)} />
          <UsageRow label="output" value={fmt(stats.lastTurn.outputTokens)} />
          {stats.lastTurn.cacheReadTokens > 0 && (
            <UsageRow label="cache hit" value={fmt(stats.lastTurn.cacheReadTokens)} success />
          )}
          {stats.lastTurn.cacheCreationTokens > 0 && (
            <UsageRow label="cache write" value={fmt(stats.lastTurn.cacheCreationTokens)} />
          )}
          {stats.lastTurn.reasoningTokens > 0 && (
            <UsageRow label="reasoning" value={fmt(stats.lastTurn.reasoningTokens)} />
          )}
        </div>

        {/* Session 累積 */}
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-fg-subtle">
            <span>{t('rightSidebar.session')}</span>
            <span className="font-mono text-fg-subtle">· {stats.turns} turns</span>
          </div>
          <UsageRow
            label={t('rightSidebar.cost')}
            value={`$${stats.cumulative.costUsd.toFixed(4)}`}
            highlight
          />
          <UsageRow
            label={t('rightSidebar.totalTokens')}
            value={fmt(
              stats.cumulative.inputTokens +
                stats.cumulative.outputTokens +
                stats.cumulative.cacheReadTokens +
                stats.cumulative.cacheCreationTokens,
            )}
          />
          {stats.cumulative.cacheReadTokens > 0 && (
            <UsageRow
              label={t('rightSidebar.cacheHitRate')}
              value={`${cacheHitPct.toFixed(1)}%`}
              success
            />
          )}
        </div>

        {/* Context window — bar */}
        {stats.contextMax > 0 && (
          <div>
            <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-fg-subtle">
              <span>{t('rightSidebar.contextWindow')}</span>
              <span className="font-mono">
                {fmt(stats.contextUsed)} / {fmt(stats.contextMax)}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-bg-hover">
              <div
                className={`h-full transition-all ${
                  contextPct > 80
                    ? 'bg-error'
                    : contextPct > 50
                      ? 'bg-warning'
                      : 'bg-accent'
                }`}
                style={{ width: `${Math.min(100, contextPct).toFixed(1)}%` }}
              />
            </div>
            <div className="mt-0.5 text-right font-mono text-[10px] text-fg-subtle">
              {contextPct.toFixed(1)}%
            </div>
          </div>
        )}
      </div>
    </Section>
  )
}

function UsageRow({
  label,
  value,
  highlight,
  success,
}: {
  label: string
  value: string
  highlight?: boolean
  success?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between py-0.5">
      <span className="text-fg-muted">{label}</span>
      <span
        className={`font-mono ${
          highlight ? 'text-fg-base' : success ? 'text-success' : 'text-fg-muted'
        }`}
      >
        {value}
      </span>
    </div>
  )
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return n.toString()
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
        {title}
      </h3>
      {children}
    </section>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-bg-hover px-2 py-3 text-center text-[11px] text-fg-subtle">
      {children}
    </div>
  )
}

/** 訊息底部 inline 檔案卡(被 MessageBubble 用)— 只顯結果產物,不顯腳本中間檔。 */
export function InlineFileCards({
  toolCalls,
  messageText,
}: {
  toolCalls: Array<{
    toolName: string
    input?: Record<string, unknown>
    status: string
    text?: string
  }>
  messageText?: string
}) {
  const files = useMemo(() => {
    const fromTools = extractWorkingFiles(toolCalls)
    // Inline card 嚴格只顯「結果產物」 — 過濾 wrote/edited 內非 output 的 path
    const filtered = fromTools.filter(
      (f) => f.action === 'opened' || isOutputFile(f.path),
    )
    // 補上從 message text 抽出的 output paths(model 在文字內提到但沒 open_path)
    const seen = new Set(filtered.map((f) => f.path))
    if (messageText) {
      for (const p of outputPathsFromText(messageText)) {
        if (!seen.has(p)) {
          filtered.push({ path: p, action: 'opened' })
          seen.add(p)
        }
      }
    }
    return filtered
  }, [toolCalls, messageText])
  if (files.length === 0) return null
  return (
    <div className="mt-2 flex flex-col gap-2">
      {files.map((f) => (
        <div
          key={f.path}
          className="flex items-center gap-3 rounded-xl border border-bg-hover bg-bg-panel p-3"
        >
          <FileText size={28} className="shrink-0 text-fg-muted" strokeWidth={1.5} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-fg-base">
              {f.path.split('/').pop()}
            </div>
            <div className="truncate text-[11px] text-fg-subtle">
              {extLabel(f.path)}
            </div>
          </div>
          <button
            type="button"
            onClick={() => window.shellApi.openPath(f.path)}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
            title={f.path}
          >
            <ExternalLink size={14} />
            <span>Open</span>
          </button>
          <button
            type="button"
            onClick={() => window.shellApi.revealInFinder(f.path)}
            className="flex shrink-0 items-center justify-center rounded-lg border border-bg-hover bg-bg-input p-2 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            title="Show in Finder"
          >
            <Folder size={14} />
          </button>
        </div>
      ))}
    </div>
  )
}

function extLabel(path: string): string {
  const dot = path.lastIndexOf('.')
  if (dot < 0) return path
  const ext = path.slice(dot + 1).toUpperCase()
  const map: Record<string, string> = {
    PPTX: 'Presentation · PPTX',
    PPT: 'Presentation · PPT',
    DOCX: 'Document · DOCX',
    DOC: 'Document · DOC',
    XLSX: 'Spreadsheet · XLSX',
    XLS: 'Spreadsheet · XLS',
    PDF: 'Document · PDF',
    PNG: 'Image · PNG',
    JPG: 'Image · JPG',
    JPEG: 'Image · JPEG',
    GIF: 'Image · GIF',
    SVG: 'Image · SVG',
    MP4: 'Video · MP4',
    MOV: 'Video · MOV',
    MP3: 'Audio · MP3',
    ZIP: 'Archive · ZIP',
    HTML: 'Web · HTML',
    MD: 'Markdown',
    CSV: 'Data · CSV',
    JSON: 'Data · JSON',
  }
  return map[ext] ?? ext
}
