import { useEffect, useRef, useState } from 'react'
import {
  BookCheck,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Copy,
  Download,
  FastForward,
  FileText,
  Gauge,
  Hand,
  Layers,
  Mic,
  Paperclip,
  Repeat,
  Send,
  Target,
  Users,
  Sparkles,
  Square,
  X,
  type LucideIcon,
} from 'lucide-react'

import type { Attachment, SkillListItem } from '../api/agent'
import {
  createConversation,
  fetchModels,
  getContextBreakdown,
  listSkills,
  setPermissionMode as rpcSetPermissionMode,
  sttTranscribe,
} from '../api/agent'
import { useCompactConversation } from '../hooks/useAgent'
import { exportAllSessions } from '../lib/exportTranscript'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'
import { useSettingsStore, type PermissionMode } from '../store/settings'

type Props = {
  onSend: (text: string, attachments?: Attachment[]) => Promise<void>
  onAbort: () => Promise<void>
}

const SUPPORTED_MIME = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']

/** Slash command 註冊表 — InputBox 偵測 / 開頭時顯示 autocomplete popover。
 *  之後加新指令在這 list 加一筆即可。 */
type SlashCommand = {
  name: string
  icon: LucideIcon
  /** 短副標題(popover 內每筆下方顯示)。 */
  subtitle: string
  /** 後面要接的 args 樣板提示,如 '[interval] <prompt>'。User 打完命令名按空格
   *  / 還沒打空格時,以灰字 ghost-text 形式顯在游標後。 */
  argsHint?: string
  /** 'client'(預設)= InputBox 直接 dispatch;'skill' = 動態載入的 bundled / user
   *  skill,不走 client-dispatch,送 LLM 由 Skill tool 載入。 */
  kind?: 'client' | 'skill'
}
/** 走 client-side dispatch 的 slash(從輸入框直接執行,不送 LLM)。
 *  /loop 不在這 — 它需要 LLM 看到原 prompt + 載 bundled `loop` skill 解析。 */
const CLIENT_SLASH_NAMES = new Set([
  '/compact',
  '/add-files',
  '/export',
  '/context',
  '/schedule',
  '/plan',
])

// Quick prompts(Phase 31-P)— empty state 顯,點 chip 自動填進 input。
// 涵蓋 explore / search / web / general 四類示範常用工具
type QuickPrompt = {
  key: string
  icon: LucideIcon
  labelKey: string
  hintKey: string
  textKey: string
}

const QUICK_PROMPTS: QuickPrompt[] = [
  {
    key: 'explore',
    icon: BookCheck,  // 暫用 BookCheck,後面換 Compass 更貼切
    labelKey: 'quickPrompt.explore.label',
    hintKey: 'quickPrompt.explore.hint',
    textKey: 'quickPrompt.explore.text',
  },
  {
    key: 'todos',
    icon: Target,
    labelKey: 'quickPrompt.todos.label',
    hintKey: 'quickPrompt.todos.hint',
    textKey: 'quickPrompt.todos.text',
  },
  {
    key: 'web',
    icon: Gauge,
    labelKey: 'quickPrompt.web.label',
    hintKey: 'quickPrompt.web.hint',
    textKey: 'quickPrompt.web.text',
  },
  {
    key: 'plan',
    icon: Users,
    labelKey: 'quickPrompt.plan.label',
    hintKey: 'quickPrompt.plan.hint',
    textKey: 'quickPrompt.plan.text',
  },
]

const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: '/compact',
    icon: Layers,
    subtitle: '壓縮對話歷史,釋出 context tokens',
  },
  {
    name: '/add-files',
    icon: Paperclip,
    subtitle: '開啟檔案選擇器加 attachments',
  },
  {
    name: '/export',
    icon: Download,
    subtitle: '把全部對話匯出到 ~/Downloads (markdown + JSON + 附件)',
  },
  {
    name: '/context',
    icon: Gauge,
    subtitle: '顯示當前 context window 用量分配',
  },
  {
    name: '/schedule',
    icon: Clock,
    subtitle: '管理排程任務(個人 / 專案)',
  },
  {
    name: '/plan',
    icon: BookCheck,
    subtitle: '進入 Plan Mode — 先擬計畫,user 批准才動手',
  },
  {
    name: '/loop',
    icon: Repeat,
    subtitle: '在此對話定期重跑 — 例:/loop 5m 檢查 PR',
    argsHint: '[interval] <prompt>',
  },
  {
    name: '/goal',
    icon: Target,
    subtitle: '持續推進到達標自動停 — 例:/goal 把測試跑到全綠',
    argsHint: '<objective>',
  },
  {
    name: '/agent',
    icon: Users,
    subtitle: '平行 spawn sub-agent — 需先在 Settings 啟用 Agent 工具',
    argsHint: '<task>',
  },
]
const MAX_BYTES = 20 * 1024 * 1024 // 20 MB raw 上限(再大連 canvas 都吃不下)
// Provider 限制(最嚴的是 Anthropic 5 MB base64);壓到 base64 < 4 MB 留 safety margin
const TARGET_BASE64_BYTES = 4 * 1024 * 1024
const COMPRESS_TRIGGER_BYTES = 1 * 1024 * 1024  // raw 超過 1MB 才走 canvas 壓縮
const COMPRESS_MAX_EDGE = 2048
const COMPRESS_QUALITY = 0.85

// Text-file drop(Phase 31-N)— 拖進來自動 inject 進 prompt
const TEXT_FILE_MAX_BYTES = 500 * 1024  // 500 KB,太大會吃掉 LLM context budget
const TEXT_EXTENSIONS = new Set([
  'txt', 'md', 'markdown', 'rst', 'log', 'csv', 'tsv', 'env',
  'py', 'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs',
  'json', 'yaml', 'yml', 'toml', 'ini', 'cfg',
  'html', 'htm', 'xml', 'css', 'scss', 'less',
  'go', 'rs', 'java', 'kt', 'swift', 'rb', 'php', 'lua',
  'c', 'cpp', 'cc', 'h', 'hpp', 'm', 'mm',
  'sh', 'bash', 'zsh', 'fish', 'ps1',
  'sql', 'graphql', 'proto', 'dockerfile',
  'gitignore', 'gitattributes', 'editorconfig',
])

type TextAttachment = {
  filename: string
  /** LLM 看到的最終 path:
   *  - 拖 workspace 內檔 → 原 path
   *  - 拖 workspace 外檔 → sidecar copy 後的新 path(<workspace>/.orion/uploads/...)
   *  - File picker → 永遠是 uploads dir 內的 copy */
  path: string
  size: number
  /** sidecar 是否 copy 過(UI chip 顯不同顏色 / hover hint) */
  copied: boolean
  /** 是否在 workspace 內(原檔可被 LLM Edit 改) */
  inWorkspace: boolean
}

function isLikelyTextFile(f: File): boolean {
  if (f.type.startsWith('text/')) return true
  if (f.type === 'application/json' || f.type === 'application/xml') return true
  if (f.type.startsWith('image/')) return false
  // mime 拿不到時用副檔名
  const ext = f.name.toLowerCase().split('.').pop() || ''
  if (TEXT_EXTENSIONS.has(ext)) return true
  // 無副檔名常見 dotfile / Dockerfile / Makefile 等
  const base = f.name.toLowerCase().replace(/^\./, '')
  if (['dockerfile', 'makefile', 'readme', 'license', 'changelog'].includes(base)) return true
  return false
}

// ─── @ mention detection(Phase 31-O)──────────────────────────────

type MentionContext = {
  /** @file: 拖檔 / 路徑 引用,@skill: 載 skill */
  mode: 'file' | 'skill'
  /** `:` 後面 user 還在打的 query string */
  query: string
  /** `@` 在 text 內的 index(replace 時用) */
  startIdx: number
  /** Cursor 位置(replace end) */
  endIdx: number
}

/** 從 cursor 往回掃 `@`,判斷現在是否在 mention 中。
 *  條件:`@` 在 string 開頭 或 前一字是 whitespace,從 `@` 到 cursor 之間
 *  沒 whitespace。 */
function detectMention(text: string, cursorPos: number): MentionContext | null {
  let i = cursorPos
  while (i > 0) {
    const c = text[i - 1]
    if (c === '@') {
      // `@` 必須在 string 頭或前面是 whitespace
      if (i - 1 === 0 || /\s/.test(text[i - 2])) {
        const token = text.slice(i, cursorPos)
        if (/\s/.test(token)) return null
        // 判 mode:`skill:xxx` 切 skill,其他都 file(也接受 `file:xxx`)
        if (token.startsWith('skill:')) {
          return { mode: 'skill', query: token.slice(6), startIdx: i - 1, endIdx: cursorPos }
        }
        const fileQuery = token.startsWith('file:') ? token.slice(5) : token
        return { mode: 'file', query: fileQuery, startIdx: i - 1, endIdx: cursorPos }
      }
      return null
    }
    if (/\s/.test(c)) return null
    i--
  }
  return null
}

/** Fuzzy match — query 字串依序出現在 target 內就 hit;空 query 全 hit。 */
function fuzzyMatch(target: string, query: string): boolean {
  if (!query) return true
  const t = target.toLowerCase()
  const q = query.toLowerCase()
  let ti = 0
  for (const qc of q) {
    const found = t.indexOf(qc, ti)
    if (found < 0) return false
    ti = found + 1
  }
  return true
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

async function fileToBase64Bytes(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // dataURL prefix: `data:<mime>;base64,<b64>` — 去掉前綴只回 b64
      const i = result.indexOf(',')
      resolve(i >= 0 ? result.slice(i + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('read failed'))
    reader.readAsDataURL(f)
  })
}

/** 多行輸入 + paperclip 上傳 + send / abort 切換。Enter 送出,Shift+Enter 換行。 */
export function InputBox({ onSend, onAbort }: Props) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [textAttachments, setTextAttachments] = useState<TextAttachment[]>([])
  const [attachError, setAttachError] = useState<string | null>(null)
  // @ mention popup state(Phase 31-O)
  const [mention, setMention] = useState<MentionContext | null>(null)
  const [mentionIdx, setMentionIdx] = useState(0)
  const [workspaceFiles, setWorkspaceFiles] = useState<Array<{ relPath: string; absPath: string; size: number }>>([])
  const workspaceFilesLoadedRef = useRef(false)
  const busy = useAgentStore((s) =>
    s.sessionId ? s.busyBySession[s.sessionId] ?? false : false,
  )
  const compacting = useAgentStore((s) =>
    s.sessionId ? s.compactingBySession[s.sessionId] ?? false : false,
  )
  const triggerCompact = useCompactConversation()
  // sidecar 啟動後一直可輸入;sessionId 為 null(New chat 後)時由 useSendPrompt
  // lazy create。只有 initError(sidecar 連不上)才完全 disable。
  const initError = useAgentStore((s) => s.initError)
  const inputReady = !initError
  const messageCount = useAgentStore((s) =>
    s.sessionId ? (s.messagesBySession[s.sessionId] ?? []).length : 0,
  )
  const isEmpty = messageCount === 0
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // IME composition tracking — 注音 / 拼音中 Enter 確認候選詞時不要送出。
  const composingRef = useRef(false)

  // ─── Slash command autocomplete ────────────────────────────────────
  // popover 開條件:單行 / 開頭(text 內無換行),user 還在打或文字仍以 / 開頭。
  // Bundled / user skills 動態載入後也一併出現在 popover(cowork_visible=false 過濾掉)。
  const [skillSlashes, setSkillSlashes] = useState<SlashCommand[]>([])
  useEffect(() => {
    let cancelled = false
    // Client slash 已寫死 /loop /goal 等(自帶 argsHint 跟更精準的 subtitle),
    // 同名 skill 從動態列表過濾掉避免 popover key 撞、UX 重複。
    const clientNames = new Set(SLASH_COMMANDS.map((c) => c.name))
    listSkills(null)
      .then((r) => {
        if (cancelled) return
        const cmds: SlashCommand[] = r.skills
          .filter((s) => (s as SkillListItem & { cowork_visible?: boolean }).cowork_visible !== false)
          .filter((s) => !clientNames.has('/' + s.name))
          .map((s) => ({
            name: '/' + s.name,
            icon: Sparkles,
            subtitle: s.description || `${s.source} skill`,
            kind: 'skill' as const,
          }))
        setSkillSlashes(cmds)
      })
      .catch(() => {
        // sidecar 還沒起來 / RPC fail 時 popover 仍可顯 client slashes
      })
  }, [])
  const allSlashes = [...SLASH_COMMANDS, ...skillSlashes]
  const slashMatches = (() => {
    if (!text.startsWith('/')) return []
    if (text.includes('\n')) return []
    const query = text.toLowerCase()
    return allSlashes.filter((c) => c.name.toLowerCase().startsWith(query))
  })()
  const showSlash = slashMatches.length > 0
  const [slashIdx, setSlashIdx] = useState(0)

  // @ mention(Phase 31-O)— lazy fetch workspace files 第一次打開時。
  // Session 沒建也沒關係 — lazy create 一條(跟 drag-drop 同 pattern),
  // 才拿得到 workspace_dir 去 walk。
  useEffect(() => {
    if (!mention || mention.mode !== 'file') return
    if (workspaceFilesLoadedRef.current) return
    workspaceFilesLoadedRef.current = true
    void (async () => {
      try {
        let sid = useAgentStore.getState().sessionId
        if (!sid) {
          const settings = useSettingsStore.getState()
          sid = await createConversation(settings.selectedProvider, settings.selectedModel, {
            projectId: settings.activeProjectId,
          })
          useAgentStore.getState().setSessionId(sid)
        }
        const { listWorkspaceFiles } = await import('../api/agent')
        const r = await listWorkspaceFiles(sid)
        setWorkspaceFiles(r.files)
      } catch {
        // 忽略 — popup 顯空 state,user 仍可走 @skill: 或拖檔
        workspaceFilesLoadedRef.current = false  // 容許下次再試
      }
    })()
  }, [mention])

  /** 過濾 mention 候選清單 — file fuzzy match path,skill fuzzy match name */
  const mentionMatches = (() => {
    if (!mention) return [] as Array<{ key: string; label: string; sublabel: string; payload: { mode: 'file' | 'skill'; absPath?: string; relPath?: string; size?: number; name?: string } }>
    if (mention.mode === 'file') {
      return workspaceFiles
        .filter((f) => fuzzyMatch(f.relPath, mention.query))
        .slice(0, 12)
        .map((f) => ({
          key: f.absPath,
          label: f.relPath,
          sublabel: humanSize(f.size),
          payload: { mode: 'file' as const, absPath: f.absPath, relPath: f.relPath, size: f.size },
        }))
    }
    return skillSlashes
      .map((s) => s.name.replace(/^\//, ''))
      .filter((name) => fuzzyMatch(name, mention.query))
      .slice(0, 12)
      .map((name) => ({
        key: `skill:${name}`,
        label: name,
        sublabel: 'skill',
        payload: { mode: 'skill' as const, name },
      }))
  })()
  // popup 開條件 — mention 在就開(empty matches 也顯空 state,user 才知道
  // 自己打的 query 沒命中而不是 popup 沒觸發)
  const showMention = mention !== null

  /** file → 加進 textAttachments + 移除 @token;skill → 替換成 @skill:name 字面值 */
  async function pickMention(item: typeof mentionMatches[number]) {
    if (!mention) return
    const before = text.slice(0, mention.startIdx)
    const after = text.slice(mention.endIdx)
    const p = item.payload
    if (p.mode === 'file' && p.absPath) {
      const absPath = p.absPath
      const relPath = p.relPath ?? ''
      const fileSize = p.size ?? 0
      const newText = before + after
      setText(newText)
      if (textareaRef.current) {
        textareaRef.current.value = newText
        requestAnimationFrame(() => {
          textareaRef.current?.setSelectionRange(mention.startIdx, mention.startIdx)
          textareaRef.current?.focus()
        })
      }
      const sid = useAgentStore.getState().sessionId
      if (!sid) {
        setMention(null)
        return
      }
      try {
        const { prepareAttachmentDrop } = await import('../api/agent')
        const staged = await prepareAttachmentDrop(sid, absPath)
        setTextAttachments((prev) => [...prev, {
          filename: relPath.split('/').pop() || absPath || 'file',
          path: staged.finalPath,
          size: fileSize,
          copied: staged.copied,
          inWorkspace: staged.inWorkspace,
        }])
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setAttachError(msg)
      }
      setMention(null)
      return
    }
    if (p.mode === 'skill' && p.name) {
      const inserted = `@skill:${p.name}`
      const newText = before + inserted + after
      setText(newText)
      if (textareaRef.current) {
        textareaRef.current.value = newText
        const newPos = mention.startIdx + inserted.length
        requestAnimationFrame(() => {
          textareaRef.current?.setSelectionRange(newPos, newPos)
          textareaRef.current?.focus()
        })
      }
      setMention(null)
    }
  }

  // Ghost-text hint:user 打完整 cmd 名稱(可帶 1 個 trailing space)時,把 argsHint
  // 以灰字接在後面顯示。如 `/loop` → 顯 `[interval] <prompt>`。
  const activeArgsHint = (() => {
    const m = text.match(/^(\/[\w-]+)( ?)$/)
    if (!m) return null
    const cmd = SLASH_COMMANDS.find((c) => c.name === m[1])
    if (!cmd?.argsHint) return null
    return (m[2] ? '' : ' ') + cmd.argsHint
  })()
  // text 變動把 idx 拉回有效範圍
  useEffect(() => {
    if (slashIdx >= slashMatches.length) setSlashIdx(0)
  }, [slashMatches.length, slashIdx])

  // 鍵盤切換 active item 時把它 scroll 進 popover 視野(↑↓ 走出 max-h-72
  // 看不到 highlight 移動,user 以為沒反應)
  const slashItemRefs = useRef<Array<HTMLButtonElement | null>>([])
  useEffect(() => {
    if (!showSlash) return
    const el = slashItemRefs.current[slashIdx]
    if (el) el.scrollIntoView({ block: 'nearest' })
  }, [slashIdx, showSlash])

  function pickSlash(cmd: SlashCommand) {
    setText(cmd.name + ' ')
    // 不立即送出 — 給 user 看一眼,Enter 才真的觸發
    setSlashIdx(0)
    requestAnimationFrame(() => {
      textareaRef.current?.focus()
    })
  }

  const canSend =
    !busy && !compacting && inputReady &&
    (text.trim().length > 0 || attachments.length > 0 || textAttachments.length > 0)

  /** Slash command 分派 — 不送 prompt,直接執行對應動作。Tab 補字 + Enter
   *  popover 選 + handleSubmit 精準匹配三個入口都走這。 */
  async function executeSlashCommand(name: string): Promise<void> {
    setText('')
    setAttachError(null)
    if (textareaRef.current) textareaRef.current.value = ''
    autoResize()
    if (name === '/compact') {
      await triggerCompact()
    } else if (name === '/add-files') {
      fileInputRef.current?.click()
    } else if (name === '/export') {
      try {
        const sid = useAgentStore.getState().sessionId
        const savedPath = await exportAllSessions(sid)
        if (savedPath && sid) {
          console.log('[export] saved to', savedPath)
          // Per-session 紀錄到 RightSidebar 工作資料夾
          useAgentStore.getState().addExtraOutputFile(sid, savedPath)
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setAttachError(`匯出失敗:${msg}`)
      }
    } else if (name === '/schedule') {
      useSettingsStore.getState().openSettings('schedules')
    } else if (name === '/plan') {
      // Toggle Plan Mode for current session
      try {
        const sid = useAgentStore.getState().sessionId
        if (!sid) {
          setAttachError('還沒對話 — 先送一句話建立 session 再進 Plan Mode')
          return
        }
        const current = useAgentStore.getState().planModeStatusBySession[sid] || 'idle'
        const { setPlanMode } = await import('../api/agent')
        if (current === 'idle') {
          await setPlanMode(sid, true)
          useAgentStore.getState().setPlanModeStatus(sid, 'pending')
        } else {
          await setPlanMode(sid, false)
          useAgentStore.getState().setPlanModeStatus(sid, 'idle')
          useAgentStore.getState().clearPendingPlanApproval(sid)
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setAttachError(`/plan 失敗:${msg}`)
      }
    } else if (name === '/context') {
      try {
        const sid = useAgentStore.getState().sessionId
        if (!sid) {
          setAttachError('還沒對話 — 先送一句話建立 session')
          return
        }
        // 把使用者 settings 內的 threshold 帶過去,sidecar 才能正確算 buffer
        const threshold = useSettingsStore.getState().autoCompactThreshold
        const report = await getContextBreakdown(sid, {
          autoCompactThreshold: threshold,
        })
        if (report) {
          useAgentStore.getState().appendContextReportCard(sid, report)
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setAttachError(`/context 失敗:${msg}`)
      }
    }
  }

  async function handleSubmit() {
    if (!canSend) return
    const payload = text
    const att = attachments
    const texts = textAttachments
    const trimmed = payload.trim()
    // 精準匹配 client-side slash command(無 attachment 時)— 例:user 打完整 /compact 按 Enter
    // /loop 跟所有 skill 不在這 list — 它們一律送 LLM(loop / skillify 等由 LLM 自己載 skill 解析)
    if (!att.length && !texts.length && trimmed.startsWith('/')) {
      const cmd = SLASH_COMMANDS.find((c) => c.name === trimmed)
      if (cmd && CLIENT_SLASH_NAMES.has(cmd.name)) {
        await executeSlashCommand(cmd.name)
        return
      }
    }
    setText('')
    setAttachments([])
    setTextAttachments([])
    setAttachError(null)
    setMention(null)
    if (textareaRef.current) {
      textareaRef.current.value = ''
    }
    autoResize()
    // @skill:xxx 偵測 — 在 prefix 加 hint 提示 LLM 用 Skill tool 載
    // (我們不 pre-resolve,讓 LLM 看到 token 自己決定要不要 load)
    const skillRefs = Array.from(payload.matchAll(/(?:^|\s)@skill:([\w-]+)/g)).map((m) => m[1])
    const uniqueSkills = Array.from(new Set(skillRefs))

    // 文字檔 prefix:只列 path + size + workspace 狀態,**不** prescribe
    // 怎麼用。LLM 看 size 自己決定:
    //   - KB 級小檔 → 直接 Read 進 context
    //   - MB+ 大檔 → peek 結構後寫 Bash / Python / jq script 處理
    //   - 100MB+ → 必走 streaming(整檔 Read 會炸 context)
    // 不寫死「Read 看」避免綁死 LLM workflow(thanks user feedback)
    let finalPrompt = payload
    const prefixParts: string[] = []
    if (texts.length) {
      const lines = texts.map((t) => {
        const sizeStr = humanSize(t.size)
        const note = t.inWorkspace
          ? `${sizeStr}, in workspace — editable in place`
          : `${sizeStr}, copied to uploads — original preserved`
        return `- ${t.path} (${note})`
      }).join('\n')
      prefixParts.push(`[User attached files (decide how to use based on the task and file size — small files: Read; large files: peek first then process via Bash / Python / jq to save context):\n${lines}\n]`)
    }
    if (uniqueSkills.length) {
      prefixParts.push(`[User referenced skills via @skill: tokens: ${uniqueSkills.join(', ')}. Load them via the Skill tool if relevant to the request.]`)
    }
    if (prefixParts.length) {
      finalPrompt = prefixParts.join('\n') + (payload ? `\n${payload}` : '')
    }
    await onSend(finalPrompt, att.length ? att : undefined)
  }

  function autoResize() {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setAttachError(null)
    const addedImages: Attachment[] = []
    const addedTexts: TextAttachment[] = []
    for (const f of Array.from(files)) {
      // 圖片 — 走原本 attachment 路徑
      if (SUPPORTED_MIME.includes(f.type)) {
        if (f.size > MAX_BYTES) {
          setAttachError(t('input.attach.tooBig', { name: f.name }))
          continue
        }
        try {
          const { base64, mediaType } =
            f.size > COMPRESS_TRIGGER_BYTES
              ? await compressImage(f)
              : { base64: await fileToBase64(f), mediaType: f.type }
          addedImages.push({
            media_type: mediaType,
            data: base64,
            preview_url: `data:${mediaType};base64,${base64}`,
            filename: f.name,
          })
        } catch {
          setAttachError(t('input.attach.readFail', { name: f.name }))
        }
        continue
      }
      // 文字檔(code / markdown / json / ...)— 透過 sidecar staging,
      // 拿到 LLM 看的 path(可能是原檔或 workspace copy)
      if (isLikelyTextFile(f)) {
        if (f.size > TEXT_FILE_MAX_BYTES) {
          setAttachError(t('input.attach.textTooBig', { name: f.name }))
          continue
        }
        // Lazy-create session — user drop 檔比 send 早,要先建 session 才有
        // sid 可以給 sidecar staging RPC
        let sid = useAgentStore.getState().sessionId
        if (!sid) {
          try {
            const settings = useSettingsStore.getState()
            sid = await createConversation(settings.selectedProvider, settings.selectedModel, {
              projectId: settings.activeProjectId,
            })
            useAgentStore.getState().setSessionId(sid)
          } catch (e) {
            const msg = e instanceof Error ? e.message : String(e)
            setAttachError(`session create failed: ${msg}`)
            continue
          }
        }
        try {
          const sourcePath = window.shellApi?.getPathForFile?.(f) || ''
          const { prepareAttachmentDrop, saveUploadedAttachment } = await import('../api/agent')
          const staged = sourcePath
            ? await prepareAttachmentDrop(sid, sourcePath)
            : await saveUploadedAttachment(sid, f.name, await fileToBase64Bytes(f))
          if (!staged.finalPath) {
            setAttachError(t('input.attach.readFail', { name: f.name }))
            continue
          }
          addedTexts.push({
            filename: f.name,
            path: staged.finalPath,
            size: f.size,
            copied: staged.copied,
            inWorkspace: staged.inWorkspace,
          })
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e)
          setAttachError(t('input.attach.readFail', { name: `${f.name}: ${msg}` }))
        }
        continue
      }
      setAttachError(t('input.attach.unsupported', { name: f.name }))
    }
    if (addedImages.length) setAttachments((prev) => [...prev, ...addedImages])
    if (addedTexts.length) setTextAttachments((prev) => [...prev, ...addedTexts])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function removeAttachment(idx: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== idx))
  }

  function removeTextAttachment(idx: number) {
    setTextAttachments((prev) => prev.filter((_, i) => i !== idx))
  }

  const [dragOver, setDragOver] = useState(false)

  // Safety net:window-level dragend / drop / mouseup 一律 reset dragOver。
  // 避免 user drag 出 InputBox 外才 release,onDragLeave 沒精準 fire 導致
  // 藍框 stuck 在 UI 上。
  useEffect(() => {
    const reset = () => setDragOver(false)
    window.addEventListener('dragend', reset)
    window.addEventListener('drop', reset)
    window.addEventListener('mouseup', reset)
    return () => {
      window.removeEventListener('dragend', reset)
      window.removeEventListener('drop', reset)
      window.removeEventListener('mouseup', reset)
    }
  }, [])

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    if (!inputReady) return
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files)
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    if (!dragOver) setDragOver(true)
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    // 用 relatedTarget(離開時新進入的元素)判斷:不在 wrapper 內就 reset
    const related = e.relatedTarget as Node | null
    if (!related || !e.currentTarget.contains(related)) {
      setDragOver(false)
    }
  }

  const placeholder = !inputReady
    ? t('input.placeholder.disabled')
    : busy
      ? t('input.placeholder.busy')
      : isEmpty
        ? t('input.placeholder.empty')
        : t('input.placeholder.normal')

  return (
    <div
      className={`bg-bg-base px-6 py-4 transition-colors ${
        isEmpty ? '' : 'border-t border-bg-hover'
      } ${dragOver ? 'bg-accent/10 ring-2 ring-inset ring-accent' : ''}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <div className="mx-auto max-w-3xl">
        {/* Empty-state hero — 跟 Claude Cowork 一致,大標題 + subtitle */}
        {isEmpty && (
          <>
            <div className="mb-6 flex items-start gap-3">
              <Sparkles size={28} className="mt-1 shrink-0 text-accent" />
              <div>
                <h2 className="text-2xl font-semibold tracking-tight text-fg-base">
                  {t('input.hero.title')}
                </h2>
                <p className="mt-1 text-sm text-fg-muted underline decoration-fg-subtle underline-offset-4">
                  {t('input.hero.subtitle')}
                </p>
              </div>
            </div>
            {/* Quick prompts — 點 chip 自動填進 input,user 可改再送 */}
            <div className="mb-4 grid grid-cols-2 gap-2">
              {QUICK_PROMPTS.map((qp) => {
                const Icon = qp.icon
                return (
                  <button
                    key={qp.key}
                    type="button"
                    onClick={() => {
                      const promptText = t(qp.textKey)
                      setText(promptText)
                      requestAnimationFrame(() => {
                        textareaRef.current?.focus()
                        // cursor 移到最尾
                        textareaRef.current?.setSelectionRange(promptText.length, promptText.length)
                      })
                      autoResize()
                    }}
                    className="flex items-start gap-2 rounded-xl border border-bg-hover bg-bg-panel px-3 py-2.5 text-left text-xs hover:border-accent/30 hover:bg-bg-hover"
                  >
                    <Icon size={14} className="mt-0.5 shrink-0 text-fg-muted" />
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate font-medium text-fg-base">{t(qp.labelKey)}</span>
                      <span className="truncate text-fg-muted">{t(qp.hintKey)}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          </>
        )}

        {/* Attachment thumbnails */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachments.map((a, i) => (
              <div
                key={i}
                className="relative h-20 w-20 overflow-hidden rounded-lg border border-bg-hover bg-bg-panel"
              >
                <img
                  src={a.preview_url}
                  alt={a.filename || 'attachment'}
                  className="h-full w-full object-cover"
                />
                <button
                  type="button"
                  onClick={() => removeAttachment(i)}
                  className="absolute right-0.5 top-0.5 rounded-full bg-bg-base/80 p-0.5 text-fg-base hover:bg-error/40 hover:text-error"
                  title={t('input.attach.remove')}
                >
                  <X size={12} />
                </button>
                {a.filename && (
                  <div
                    className="absolute bottom-0 left-0 right-0 truncate bg-bg-base/70 px-1 text-[10px] text-fg-muted"
                    title={a.filename}
                  >
                    {a.filename}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Text-file drop chips(Phase 31-N)— 拖進來的 code / markdown 等
            檔案。LLM 看到的是 path(in-workspace 原檔 / uploads dir copy),
            不 inline content。Hover 顯完整 path 跟 copy 狀態。 */}
        {textAttachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {textAttachments.map((tf, i) => (
              <div
                key={i}
                className={`group relative flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${
                  tf.inWorkspace
                    ? 'border-accent/30 bg-accent/5'
                    : 'border-bg-hover bg-bg-panel'
                }`}
                title={
                  tf.inWorkspace
                    ? `${tf.path}\n(workspace 內 — LLM 可 Edit 原檔)`
                    : `${tf.path}\n(已 copy 到 uploads — 原檔不會被改)`
                }
              >
                <FileText size={14} className="shrink-0 text-fg-muted" />
                <span className="max-w-[200px] truncate font-mono">{tf.filename}</span>
                <span className="text-[10px] text-fg-subtle">
                  {(tf.size / 1024).toFixed(1)} KB
                </span>
                {tf.copied && (
                  <span className="rounded bg-bg-hover px-1 text-[9px] uppercase text-fg-subtle">
                    copy
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => removeTextAttachment(i)}
                  className="ml-1 rounded p-0.5 text-fg-muted opacity-0 hover:bg-error/40 hover:text-error group-hover:opacity-100"
                  title={t('input.attach.remove')}
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        {attachError && (
          <p className="mb-1 px-2 text-xs text-error">⚠ {attachError}</p>
        )}

        {/* @ mention popup(Phase 31-O)— 在輸入框上方,跟 slash popover
            互斥(text 開頭是 `/` 才開 slash;@ 不在開頭也能觸發) */}
        {showMention && (
          <div className="scrollbar-thin mb-2 max-h-72 overflow-y-auto rounded-2xl border border-bg-hover bg-bg-panel p-1.5 shadow-xl">
            <div className="border-b border-bg-hover px-3 py-1 text-[10px] uppercase tracking-wide text-fg-subtle">
              {mention?.mode === 'skill' ? 'Skills' : 'Files'}
              {mention?.mode === 'file' && workspaceFiles.length === 0 && (
                <span className="ml-2 text-fg-muted normal-case">— 載入中 / 沒檔</span>
              )}
            </div>
            {mentionMatches.length === 0 && (
              <div className="px-3 py-2 text-xs text-fg-muted">
                {mention?.mode === 'file'
                  ? (workspaceFiles.length === 0
                      ? '工作區還沒設定,或正在載入。打 @skill: 改載 skill。'
                      : `沒檔案符合 "${mention.query}" — 試別的關鍵字`)
                  : `沒 skill 符合 "${mention.query}"`}
              </div>
            )}
            {mentionMatches.map((item, i) => {
              const active = i === mentionIdx
              return (
                <button
                  key={item.key}
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); void pickMention(item) }}
                  onMouseEnter={() => setMentionIdx(i)}
                  className={`flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-xs transition-colors ${
                    active ? 'bg-bg-hover' : 'bg-transparent hover:bg-bg-hover/50'
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    {mention?.mode === 'skill' ? (
                      <Sparkles size={12} className="shrink-0 text-fg-muted" />
                    ) : (
                      <FileText size={12} className="shrink-0 text-fg-muted" />
                    )}
                    <span className="truncate font-mono">{item.label}</span>
                  </span>
                  <span className="shrink-0 text-[10px] text-fg-subtle">{item.sublabel}</span>
                </button>
              )
            })}
            <div className="mt-1 border-t border-bg-hover px-3 pt-1.5 text-[10px] text-fg-subtle">
              <kbd className="font-mono">↑↓</kbd> 切換 ·{' '}
              <kbd className="font-mono">Tab/Enter</kbd> 選 ·{' '}
              <kbd className="font-mono">Esc</kbd> 取消 ·{' '}
              <span className="text-fg-muted">type `@skill:` for skills</span>
            </div>
          </div>
        )}

        {/* Slash command autocomplete popover — / 開頭時顯示在輸入框上方 */}
        {showSlash && (
          <div className="scrollbar-thin mb-2 max-h-72 overflow-y-auto rounded-2xl border border-bg-hover bg-bg-panel p-1.5 shadow-xl">
            {slashMatches.map((cmd, i) => {
              const active = i === slashIdx
              const Icon = cmd.icon
              const isSkill = cmd.kind === 'skill'
              // 分組標題:第一個 skill 上方插 divider
              const prevIsSkill = i > 0 && slashMatches[i - 1].kind === 'skill'
              const showDivider = isSkill && !prevIsSkill && i > 0
              return (
                <div key={cmd.name}>
                  {showDivider && (
                    <div className="mt-1 border-t border-bg-hover/60 px-3 py-1 text-[10px] uppercase tracking-wide text-fg-subtle">
                      Skills
                    </div>
                  )}
                  <button
                    ref={(el) => { slashItemRefs.current[i] = el }}
                    type="button"
                    onMouseDown={(e) => {
                      // mousedown 比 click 早 — 避免 blur 把 popover 收起
                      e.preventDefault()
                      pickSlash(cmd)
                    }}
                    onMouseEnter={() => setSlashIdx(i)}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors ${
                      active ? 'bg-bg-hover' : 'bg-transparent hover:bg-bg-hover/50'
                    }`}
                  >
                    <Icon size={18} className="shrink-0 text-fg-muted" />
                    <div className="flex min-w-0 flex-col">
                      <span className="font-mono text-sm text-fg-base">{cmd.name.slice(1)}</span>
                      <span className="truncate text-xs text-fg-muted">{cmd.subtitle}</span>
                    </div>
                  </button>
                </div>
              )
            })}
            <div className="mt-1 border-t border-bg-hover px-3 pt-1.5 text-[10px] text-fg-subtle">
              Type to filter · <kbd className="font-mono">↑↓</kbd> 切換 ·{' '}
              <kbd className="font-mono">Tab</kbd> 填入 ·{' '}
              <kbd className="font-mono">Enter</kbd> 執行 ·{' '}
              <kbd className="font-mono">Esc</kbd> 取消
            </div>
          </div>
        )}

        {/* 主框:上方 textarea,下方 toolbar(+ / Ask pill / spacer / Model pill / mic / send) */}
        <div className="flex flex-col gap-2 rounded-2xl bg-bg-input p-3">
          <div className="relative">
          {activeArgsHint && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 max-h-[200px] overflow-hidden whitespace-pre-wrap break-words px-1 py-1 text-sm leading-normal"
            >
              <span className="invisible">{text}</span>
              <span className="text-fg-subtle">{activeArgsHint}</span>
            </div>
          )}
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => {
              const newText = e.target.value
              setText(newText)
              autoResize()
              // Mention detection — cursor 位置看新 text 內是否在 @ 內
              const pos = e.target.selectionStart ?? newText.length
              const ctx = detectMention(newText, pos)
              setMention(ctx)
              setMentionIdx(0)
            }}
            onSelect={(e) => {
              // 滑鼠 / 鍵盤移動 cursor 也要重判 mention(避免 user 用方向鍵
              // 把 cursor 移出 / 進入 @ token 後 popup 沒對應更新)
              const ta = e.currentTarget
              const ctx = detectMention(ta.value, ta.selectionStart ?? 0)
              setMention(ctx)
            }}
            onCompositionStart={() => {
              composingRef.current = true
            }}
            onCompositionEnd={() => {
              composingRef.current = false
            }}
            onKeyDown={(e) => {
              // @ mention popup 開時 — 優先處理(跟 slash 互斥)。Esc 不論
              // 有沒有 matches 都讓 popup 關;navigation 鍵只在有 matches
              // 才攔(否則照常打字)
              if (showMention && e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                setMention(null)
                return
              }
              if (showMention && mentionMatches.length > 0) {
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  e.stopPropagation()
                  setMentionIdx((i) => (i + 1) % mentionMatches.length)
                  return
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  e.stopPropagation()
                  setMentionIdx((i) => (i - 1 + mentionMatches.length) % mentionMatches.length)
                  return
                }
                if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
                  if (e.key === 'Enter' && (e.nativeEvent.isComposing || composingRef.current)) {
                    // 組字中 Enter 確認候選,不選 mention
                  } else {
                    e.preventDefault()
                    e.stopPropagation()
                    void pickMention(mentionMatches[mentionIdx])
                    return
                  }
                }
                if (e.key === 'Escape') {
                  e.preventDefault()
                  e.stopPropagation()
                  setMention(null)
                  return
                }
              }
              // Slash popover 開時,navigation keys 優先處理 — 不被 IME guard 擋
              // (IME 異常沒 fire compositionEnd 時 composingRef 可能 stuck=true,
              //  ArrowDown/Up/Tab/Enter/Escape 一律穿透給 popover)
              if (showSlash && slashMatches.length > 0) {
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  e.stopPropagation()
                  setSlashIdx((i) => (i + 1) % slashMatches.length)
                  return
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  e.stopPropagation()
                  setSlashIdx((i) => (i - 1 + slashMatches.length) % slashMatches.length)
                  return
                }
                if (e.key === 'Tab') {
                  e.preventDefault()
                  e.stopPropagation()
                  pickSlash(slashMatches[slashIdx])
                  return
                }
                if (e.key === 'Escape') {
                  e.preventDefault()
                  e.stopPropagation()
                  setText('')
                  if (textareaRef.current) textareaRef.current.value = ''
                  return
                }
                // Enter 仍要 IME guard — 組字中 Enter 是確認候選詞
                if (e.key === 'Enter' && !e.shiftKey) {
                  if (e.nativeEvent.isComposing || composingRef.current) return
                  e.preventDefault()
                  e.stopPropagation()
                  const cmd = slashMatches[slashIdx]
                  if (!cmd) return
                  if (CLIENT_SLASH_NAMES.has(cmd.name)) {
                    void executeSlashCommand(cmd.name)
                  } else {
                    pickSlash(cmd)
                  }
                  return
                }
              }
              // Popover 沒開 — IME guard 用於 Enter 送出
              if (e.nativeEvent.isComposing || composingRef.current) return
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSubmit()
              }
            }}
            onPaste={(e) => {
              const items = e.clipboardData?.items
              if (!items) return
              const pasted: File[] = []
              for (const item of items) {
                if (item.kind === 'file') {
                  const f = item.getAsFile()
                  if (f) pasted.push(f)
                }
              }
              if (pasted.length) {
                e.preventDefault()
                const dt = new DataTransfer()
                pasted.forEach((f) => dt.items.add(f))
                handleFiles(dt.files)
              }
            }}
            disabled={!inputReady}
            placeholder={placeholder}
            rows={isEmpty ? 2 : 1}
            className="scrollbar-thin block w-full max-h-[200px] resize-none bg-transparent px-1 py-1 text-sm leading-normal text-fg-base placeholder:text-fg-subtle focus:outline-none disabled:cursor-not-allowed"
          />
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={!inputReady || busy}
              title={t('input.attach')}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Paperclip size={16} />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={SUPPORTED_MIME.join(',')}
              onChange={(e) => handleFiles(e.target.files)}
              className="hidden"
            />

            <PermissionModePill />

            <div className="flex-1" />

            <ModelPill />

            <MicButton
              onTranscript={(text) => {
                setText((cur) => {
                  const sep = cur && !/[\s]$/.test(cur) ? ' ' : ''
                  return cur + sep + text
                })
                // 把 textarea 帶到輸入末端,讓使用者看到剛轉錄的文字
                requestAnimationFrame(() => {
                  const ta = textareaRef.current
                  if (ta) {
                    ta.focus()
                    ta.setSelectionRange(ta.value.length, ta.value.length)
                    autoResize()
                  }
                })
              }}
              disabled={!inputReady}
            />

            {busy ? (
              <button
                type="button"
                onClick={onAbort}
                title={t('input.stop')}
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-error/20 text-error hover:bg-error/30"
              >
                <Square size={14} fill="currentColor" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!canSend}
                title={canSend ? t('input.send') : t('input.sendDisabled')}
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Send size={14} />
              </button>
            )}
          </div>
        </div>

        <FooterHint />
        <p className="mt-2 text-center text-[11px] text-fg-subtle">
          {t('input.disclaimer')}
        </p>
      </div>
    </div>
  )
}

/** Ask / Act 切換 pill — popup 兩個選項 + 描述。中途切會即時同步 sidecar。 */
function PermissionModePill() {
  const { t } = useTranslation()
  const mode = useSettingsStore((s) => s.permissionMode)
  const setModeLocal = useSettingsStore((s) => s.setPermissionMode)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  // 切 mode 時:1) 寫入本地 settings store 2) 若有 active session 推給 sidecar
  // 讓 in-flight turn 立刻響應(切到 act 會 auto-resolve pending approvals)。
  function setMode(m: PermissionMode) {
    setModeLocal(m)
    const sid = useAgentStore.getState().sessionId
    if (sid) {
      rpcSetPermissionMode(sid, m).catch(() => {
        // backend 沒接 / session 已過期都不擋本地 UI
      })
    }
  }

  // 點外面關掉 popup
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [open])

  const isAsk = mode === 'ask'
  const Icon = isAsk ? Hand : FastForward
  const label = isAsk ? t('input.askMode.pill') : t('input.actMode.pill')

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 items-center gap-1.5 rounded-lg bg-bg-hover/60 px-2.5 text-xs text-fg-base hover:bg-bg-hover"
      >
        <Icon size={13} />
        <span>{label}</span>
        <ChevronDown size={12} className="text-fg-muted" />
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-40 mb-2 w-72 overflow-hidden rounded-xl border border-bg-hover bg-bg-panel shadow-xl">
          <PermissionModeRow
            mode="ask"
            current={mode}
            icon={Hand}
            label={t('input.askMode.askLabel')}
            desc={t('input.askMode.askDesc')}
            onPick={(m) => {
              setMode(m)
              setOpen(false)
            }}
          />
          <PermissionModeRow
            mode="act"
            current={mode}
            icon={FastForward}
            label={t('input.askMode.actLabel')}
            desc={t('input.askMode.actDesc')}
            onPick={(m) => {
              setMode(m)
              setOpen(false)
            }}
          />
        </div>
      )}
    </div>
  )
}

function PermissionModeRow({
  mode,
  current,
  icon: Icon,
  label,
  desc,
  onPick,
}: {
  mode: PermissionMode
  current: PermissionMode
  icon: typeof Hand
  label: string
  desc: string
  onPick: (m: PermissionMode) => void
}) {
  const active = mode === current
  return (
    <button
      type="button"
      onClick={() => onPick(mode)}
      className="flex w-full items-start gap-3 px-3 py-3 text-left hover:bg-bg-hover"
    >
      <Icon size={16} className="mt-0.5 shrink-0 text-fg-muted" />
      <div className="flex-1">
        <div className="text-sm font-medium text-fg-base">{label}</div>
        <div className="mt-0.5 text-xs text-fg-muted">{desc}</div>
      </div>
      {active && <Check size={14} className="mt-1 shrink-0 text-accent" />}
    </button>
  )
}

/** Model pill — 點開直接列 providers / models 選,沒設 API key 的 disabled。 */
function ModelPill() {
  const { t } = useTranslation()
  const providers = useSettingsStore((s) => s.providers)
  const catalogLoaded = useSettingsStore((s) => s.catalogLoaded)
  const setCatalog = useSettingsStore((s) => s.setCatalog)
  const selectedProvider = useSettingsStore((s) => s.selectedProvider)
  const selectedModel = useSettingsStore((s) => s.selectedModel)
  const setSelectedModel = useSettingsStore((s) => s.setSelectedModel)
  const openSettings = useSettingsStore((s) => s.openSettings)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  // popup 向上開可用的高度 = button.top - 16 (留 padding)
  // empty state 時 InputBox 中央定位,popup 往上空間有限;active state 在視窗
  // 底,空間很大。動態算才不會被視窗頂裁掉。
  const [popupMaxH, setPopupMaxH] = useState<number>(400)

  // Lazy load catalog — InputBox 是 cold-start 第一個看到的 UI,user 不一定
  // 進過 Settings → Models,所以這裡也自己 fetch 一次。
  useEffect(() => {
    if (catalogLoaded) return
    fetchModels()
      .then((cat) =>
        setCatalog(
          cat.providers.map((p) => ({
            id: p.id,
            label: p.label,
            models: p.models,
            api_key_configured: p.api_key_configured,
            via_proxy: p.via_proxy,
            dynamic: p.dynamic,
          })),
        ),
      )
      .catch(() => {})
  }, [catalogLoaded, setCatalog])

  // Ollama 動態 model list — popup 打開時刷新,stale > 30s 也重抓
  const ollamaState = useSettingsStore((s) => s.ollama)
  const refreshOllama = useSettingsStore((s) => s.refreshOllama)
  useEffect(() => {
    if (!open) return
    const hasOllama = providers.some((p) => p.id === 'ollama')
    if (!hasOllama) return
    const stale = !ollamaState.lastFetched || Date.now() - ollamaState.lastFetched > 30_000
    if (stale) void refreshOllama()
  }, [open, providers, ollamaState.lastFetched, refreshOllama])

  // 點外面關掉 popup
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [open])

  // 打開時即時量 button 距視窗頂的距離,popup max-h 不超過就不會被裁
  useEffect(() => {
    if (!open) return
    const measure = () => {
      const r = btnRef.current?.getBoundingClientRect()
      if (r) setPopupMaxH(Math.max(120, r.top - 16))
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [open])

  // 找目前 model 的 label;catalog 沒 load 完就 fallback 顯 id
  const activeLabel =
    providers
      .find((p) => p.id === selectedProvider)
      ?.models.find((m) => m.id === selectedModel)?.label ?? selectedModel

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 max-w-[180px] items-center gap-1 rounded-lg px-2 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base"
      >
        <span className="truncate">{activeLabel}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <div
          className="absolute bottom-full right-0 z-40 mb-2 flex w-72 flex-col overflow-hidden rounded-xl border border-bg-hover bg-bg-panel shadow-xl"
          style={{ maxHeight: `${popupMaxH}px` }}
        >
          <div className="scrollbar-thin flex-1 overflow-y-auto">
            {!catalogLoaded ? (
              <div className="px-3 py-3 text-xs text-fg-muted">
                {t('settings.model.loading')}
              </div>
            ) : providers.length === 0 ? (
              <div className="px-3 py-3 text-xs text-error">
                {t('settings.model.failed')}
              </div>
            ) : (
              providers.map((p) => {
                // Ollama 是 dynamic provider — 用 store 的 ollamaState.models
                // 取代靜態 p.models(p.models 為空)
                const isOllama = p.id === 'ollama'
                const ollamaList = isOllama && ollamaState.models
                  ? ollamaState.models.map((om) => ({
                      id: om.name,
                      label: om.name + (om.details?.parameter_size ? ` · ${om.details.parameter_size}` : ''),
                    }))
                  : null
                const modelsToShow = ollamaList ?? p.models
                return (
                  <div key={p.id}>
                    <div className="flex items-center justify-between border-b border-bg-hover px-3 py-1.5 text-[11px] uppercase tracking-wide text-fg-subtle">
                      <span>{p.label}</span>
                      {isOllama && !ollamaState.ok && (
                        <span className="text-warning">
                          {t('settings.model.ollamaOffline')}
                        </span>
                      )}
                      {!isOllama && !p.api_key_configured && (
                        <span className="text-warning">
                          {t('settings.model.apiKeyMissing')}
                        </span>
                      )}
                      {!isOllama && p.api_key_configured && p.via_proxy && (
                        <span className="text-warning" title={t('settings.model.viaProxyHint')}>
                          ⚠ {t('settings.model.viaProxy')}
                        </span>
                      )}
                    </div>
                    {isOllama && !ollamaState.ok && (
                      <div className="px-3 py-2 text-xs text-fg-muted">
                        {ollamaState.error || t('settings.model.ollamaUnreachable')}
                      </div>
                    )}
                    {isOllama && ollamaState.ok && modelsToShow.length === 0 && (
                      <div className="px-3 py-2 text-xs text-fg-muted">
                        {t('settings.model.ollamaEmpty')}
                      </div>
                    )}
                    {modelsToShow.map((m) => {
                      const active =
                        selectedProvider === p.id && selectedModel === m.id
                      const disabled = isOllama ? !ollamaState.ok : !p.api_key_configured
                      return (
                        <button
                          key={m.id}
                          type="button"
                          disabled={disabled}
                          onClick={() => {
                            setSelectedModel(p.id, m.id)
                            setOpen(false)
                          }}
                          className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40 ${
                            active ? 'text-accent' : 'text-fg-base'
                          }`}
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            {active && <Check size={12} className="shrink-0" />}
                            <span className="truncate">{m.label}</span>
                          </span>
                          <span className="shrink-0 font-mono text-[10px] text-fg-subtle">
                            {m.id}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )
              })
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              openSettings('models')
            }}
            className="shrink-0 border-t border-bg-hover px-3 py-2 text-left text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            {t('input.modelPill.manage')}
          </button>
        </div>
      )}
    </div>
  )
}

function FooterHint() {
  const { t } = useTranslation()
  const sessionId = useAgentStore((s) => s.sessionId)
  const error = useAgentStore((s) =>
    s.sessionId ? s.errorBySession[s.sessionId] ?? null : null,
  )
  const status = useAgentStore((s) =>
    s.sessionId ? s.lastLoopStatusBySession[s.sessionId] ?? null : null,
  )
  if (error && sessionId) {
    return <ErrorBanner sessionId={sessionId} message={error} />
  }
  if (status) {
    const key = status.turns === 1 ? 'input.lastTurn.singular' : 'input.lastTurn'
    return (
      <p className="mt-1 px-2 text-xs text-fg-subtle">
        {t(key, { reason: status.reason, turns: status.turns })}
      </p>
    )
  }
  return null
}


function ErrorBanner({ sessionId, message }: { sessionId: string; message: string }) {
  const { t } = useTranslation()
  const setError = useAgentStore((s) => s.setError)
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* swallow — clipboard 在 Electron 一般能用,失敗不重要 */
    }
  }

  const handleDismiss = () => setError(sessionId, null)

  return (
    <div className="mt-1 rounded border border-error/30 bg-error/5 px-2 py-1 text-xs text-error">
      <div className="flex items-start gap-1.5">
        <span className="shrink-0">⚠</span>
        <span
          className={expanded ? 'flex-1 whitespace-pre-wrap break-words' : 'flex-1 truncate'}
          title={expanded ? undefined : message}
        >
          {message}
        </span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="shrink-0 rounded p-0.5 hover:bg-error/10"
          title={expanded ? t('error.collapse') : t('error.expand')}
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
        <button
          type="button"
          onClick={handleCopy}
          className="shrink-0 rounded p-0.5 hover:bg-error/10"
          title={copied ? t('error.copied') : t('error.copy')}
        >
          <Copy size={12} />
        </button>
        <button
          type="button"
          onClick={handleDismiss}
          className="shrink-0 rounded p-0.5 hover:bg-error/10"
          title={t('error.dismiss')}
        >
          <X size={12} />
        </button>
      </div>
    </div>
  )
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error('FileReader returned non-string'))
        return
      }
      const idx = result.indexOf(',')
      resolve(idx >= 0 ? result.slice(idx + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('read error'))
    reader.readAsDataURL(file)
  })
}

/**
 * Canvas resize + JPEG re-encode 把大圖壓到 base64 < 4 MB(Anthropic 5 MB 限制
 * 留 margin)。先試 1× edge,base64 仍超就遞減 quality / scale 多試幾輪。
 *
 * Trade-off:統一轉 JPEG 會把 PNG 的透明變黑,但 vision LLM 用例幾乎都是
 * 照片 / 截圖,透明資訊不重要。GIF 動畫被 flatten,可接受。
 */
async function compressImage(file: File): Promise<{ base64: string; mediaType: string }> {
  const img = await loadImageFromFile(file)
  const longest = Math.max(img.naturalWidth, img.naturalHeight)
  let scale = longest > COMPRESS_MAX_EDGE ? COMPRESS_MAX_EDGE / longest : 1
  let quality = COMPRESS_QUALITY

  for (let attempt = 0; attempt < 5; attempt++) {
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(img.naturalWidth * scale)
    canvas.height = Math.round(img.naturalHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas 2d context unavailable')
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const dataUrl = canvas.toDataURL('image/jpeg', quality)
    const base64 = dataUrl.split(',')[1] ?? ''
    if (base64.length <= TARGET_BASE64_BYTES) {
      return { base64, mediaType: 'image/jpeg' }
    }
    // 還太大:先降 quality,再降 scale,最後縮到 1280
    if (quality > 0.6) quality -= 0.1
    else if (scale > 0.5) scale *= 0.75
    else scale = 1280 / longest
  }
  throw new Error('cannot compress image under provider limit')
}

function loadImageFromFile(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image decode failed'))
    }
    img.src = url
  })
}

// ─── STT via MediaRecorder + OpenAI Whisper / Google Cloud STT ──────────────
//
// 點麥克風 → getUserMedia + MediaRecorder 開始錄;再點 → 停止 + base64 audio
// 送 sidecar(stt.transcribe)→ 回 transcript append 到 textarea。
// Provider 從 settings.sttProvider 拿,sidecar 用對應 env API key。
//
// 為什麼不用 webkitSpeechRecognition:Electron 沒打包 Google API key,呼叫
// 立刻 error 中止。MediaRecorder 走直連 OpenAI / Google REST 才實際能用。

const MIC_MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',  // Safari / 部分 Chromium build
]

function pickMimeType(): string {
  for (const m of MIC_MIME_CANDIDATES) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) {
      return m
    }
  }
  return 'audio/webm'
}

function MicButton({
  onTranscript,
  disabled,
}: {
  onTranscript: (text: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const locale = useSettingsStore((s) => s.locale)
  const provider = useSettingsStore((s) => s.sttProvider)
  const openaiModel = useSettingsStore((s) => s.openaiSttModel)
  const [phase, setPhase] = useState<'idle' | 'recording' | 'transcribing'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [costInfo, setCostInfo] = useState<{ duration: number; cost: number | null; model: string } | null>(null)
  const recRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const startTsRef = useRef<number>(0)

  // unmount 時收乾淨
  useEffect(() => {
    return () => {
      try {
        recRef.current?.stop()
      } catch { /* ignore */ }
      streamRef.current?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  // 自動清掉錯誤訊息 — 3s 後消失
  useEffect(() => {
    if (!error) return
    const id = setTimeout(() => setError(null), 3000)
    return () => clearTimeout(id)
  }, [error])

  // 成功 transcribe 的費用提示也 4 秒後淡掉
  useEffect(() => {
    if (!costInfo) return
    const id = setTimeout(() => setCostInfo(null), 4000)
    return () => clearTimeout(id)
  }, [costInfo])

  const sttOff = provider === 'off'

  async function start() {
    if (disabled || sttOff || phase !== 'idle') return
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mime = pickMimeType()
      const rec = new MediaRecorder(stream, { mimeType: mime })
      chunksRef.current = []
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data)
      }
      rec.onstop = async () => {
        // 釋放 mic
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        const blob = new Blob(chunksRef.current, { type: mime })
        chunksRef.current = []
        const duration = (Date.now() - startTsRef.current) / 1000
        if (blob.size < 1024) {
          setPhase('idle')
          setError(t('input.mic.tooShort'))
          return
        }
        setPhase('transcribing')
        try {
          const b64 = await blobToBase64(blob)
          const result = await sttTranscribe(
            provider as 'openai' | 'google',
            b64,
            mime,
            locale,
            provider === 'openai' ? openaiModel : undefined,
            duration,
          )
          if (result.text.trim()) onTranscript(result.text.trim())
          if (result.durationSeconds != null || result.costUsd != null) {
            setCostInfo({
              duration: result.durationSeconds ?? duration,
              cost: result.costUsd,
              model: result.model,
            })
          }
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e))
        } finally {
          setPhase('idle')
        }
      }
      startTsRef.current = Date.now()
      rec.start()
      recRef.current = rec
      setPhase('recording')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'mic unavailable')
      setPhase('idle')
    }
  }

  function stop() {
    try {
      recRef.current?.stop()
    } catch { /* ignore */ }
  }

  const label =
    phase === 'recording'
      ? t('input.mic.stop')
      : phase === 'transcribing'
        ? t('input.mic.transcribing')
        : sttOff
          ? t('input.mic.off')
          : t('input.mic.start')

  return (
    <div className="relative">
      <button
        type="button"
        onClick={phase === 'recording' ? stop : start}
        disabled={disabled || sttOff || phase === 'transcribing'}
        title={label}
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg disabled:cursor-not-allowed disabled:opacity-40 ${
          phase === 'recording'
            ? 'bg-error/20 text-error hover:bg-error/30 animate-pulse'
            : phase === 'transcribing'
              ? 'text-accent'
              : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
        }`}
      >
        <Mic size={16} className={phase === 'transcribing' ? 'animate-pulse' : ''} />
      </button>
      {error && (
        <div className="absolute bottom-full right-0 mb-1 w-64 rounded-md border border-error/40 bg-bg-base px-2 py-1 text-[11px] text-error shadow-lg">
          {error}
        </div>
      )}
      {!error && costInfo && (
        <div className="absolute bottom-full right-0 mb-1 w-64 rounded-md border border-bg-hover bg-bg-base px-2 py-1 text-[11px] text-fg-muted shadow-lg">
          {t('input.mic.cost', {
            duration: costInfo.duration.toFixed(1),
            cost: costInfo.cost != null ? `~$${costInfo.cost.toFixed(4)}` : '—',
            model: costInfo.model,
          })}
        </div>
      )}
    </div>
  )
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const r = reader.result
      if (typeof r !== 'string') {
        reject(new Error('FileReader returned non-string'))
        return
      }
      const idx = r.indexOf(',')
      resolve(idx >= 0 ? r.slice(idx + 1) : r)
    }
    reader.onerror = () => reject(reader.error ?? new Error('read failed'))
    reader.readAsDataURL(blob)
  })
}
