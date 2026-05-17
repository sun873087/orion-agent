import { useEffect, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  Download,
  FastForward,
  Gauge,
  Hand,
  Layers,
  Mic,
  Paperclip,
  Send,
  Sparkles,
  Square,
  X,
  type LucideIcon,
} from 'lucide-react'

import type { Attachment } from '../api/agent'
import {
  fetchModels,
  getContextBreakdown,
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
}
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
]
const MAX_BYTES = 20 * 1024 * 1024 // 20 MB raw 上限(再大連 canvas 都吃不下)
// Provider 限制(最嚴的是 Anthropic 5 MB base64);壓到 base64 < 4 MB 留 safety margin
const TARGET_BASE64_BYTES = 4 * 1024 * 1024
const COMPRESS_TRIGGER_BYTES = 1 * 1024 * 1024  // raw 超過 1MB 才走 canvas 壓縮
const COMPRESS_MAX_EDGE = 2048
const COMPRESS_QUALITY = 0.85

/** 多行輸入 + paperclip 上傳 + send / abort 切換。Enter 送出,Shift+Enter 換行。 */
export function InputBox({ onSend, onAbort }: Props) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [attachError, setAttachError] = useState<string | null>(null)
  const busy = useAgentStore((s) => s.busy)
  const compacting = useAgentStore((s) => s.compacting)
  const triggerCompact = useCompactConversation()
  // sidecar 啟動後一直可輸入;sessionId 為 null(New chat 後)時由 useSendPrompt
  // lazy create。只有 initError(sidecar 連不上)才完全 disable。
  const initError = useAgentStore((s) => s.initError)
  const inputReady = !initError
  const messageCount = useAgentStore((s) => s.messages.length)
  const isEmpty = messageCount === 0
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // IME composition tracking — 注音 / 拼音中 Enter 確認候選詞時不要送出。
  const composingRef = useRef(false)

  // ─── Slash command autocomplete ────────────────────────────────────
  // popover 開條件:單行 / 開頭(text 內無換行),user 還在打或文字仍以 / 開頭
  const slashMatches = (() => {
    if (!text.startsWith('/')) return []
    if (text.includes('\n')) return []
    const query = text.toLowerCase()
    return SLASH_COMMANDS.filter((c) => c.name.toLowerCase().startsWith(query))
  })()
  const showSlash = slashMatches.length > 0
  const [slashIdx, setSlashIdx] = useState(0)
  // text 變動把 idx 拉回有效範圍
  useEffect(() => {
    if (slashIdx >= slashMatches.length) setSlashIdx(0)
  }, [slashMatches.length, slashIdx])

  function pickSlash(cmd: SlashCommand) {
    setText(cmd.name + ' ')
    // 不立即送出 — 給 user 看一眼,Enter 才真的觸發
    setSlashIdx(0)
    requestAnimationFrame(() => {
      textareaRef.current?.focus()
    })
  }

  const canSend =
    !busy && !compacting && inputReady && (text.trim().length > 0 || attachments.length > 0)

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
          useAgentStore.getState().appendContextReportCard(report)
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
    const trimmed = payload.trim()
    // 精準匹配 slash command(無 attachment 時)— 例:user 打完整 /compact 按 Enter
    if (!att.length && trimmed.startsWith('/')) {
      const cmd = SLASH_COMMANDS.find((c) => c.name === trimmed)
      if (cmd) {
        await executeSlashCommand(cmd.name)
        return
      }
    }
    setText('')
    setAttachments([])
    setAttachError(null)
    // 直接清 textarea DOM value:避免 IME / React batching 時序 race
    // 讓送出後字符仍殘留在輸入框。
    if (textareaRef.current) {
      textareaRef.current.value = ''
    }
    autoResize()
    await onSend(payload, att.length ? att : undefined)
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
    const added: Attachment[] = []
    for (const f of Array.from(files)) {
      if (!SUPPORTED_MIME.includes(f.type)) {
        setAttachError(t('input.attach.unsupported', { name: f.name }))
        continue
      }
      if (f.size > MAX_BYTES) {
        setAttachError(t('input.attach.tooBig', { name: f.name }))
        continue
      }
      try {
        // 大圖(> 1MB raw)自動 canvas resize + JPEG re-encode,避免 Anthropic 5 MB
        // base64 上限把 LLM call 打回。人眼幾乎無差(2048px max edge / quality 0.85)。
        const { base64, mediaType } =
          f.size > COMPRESS_TRIGGER_BYTES
            ? await compressImage(f)
            : { base64: await fileToBase64(f), mediaType: f.type }
        added.push({
          media_type: mediaType,
          data: base64,
          preview_url: `data:${mediaType};base64,${base64}`,
          filename: f.name,
        })
      } catch {
        setAttachError(t('input.attach.readFail', { name: f.name }))
      }
    }
    if (added.length) setAttachments((prev) => [...prev, ...added])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function removeAttachment(idx: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== idx))
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

        {attachError && (
          <p className="mb-1 px-2 text-xs text-error">⚠ {attachError}</p>
        )}

        {/* Slash command autocomplete popover — / 開頭時顯示在輸入框上方 */}
        {showSlash && (
          <div className="mb-2 overflow-hidden rounded-2xl border border-bg-hover bg-bg-panel p-1.5 shadow-xl">
            {slashMatches.map((cmd, i) => {
              const active = i === slashIdx
              const Icon = cmd.icon
              return (
                <button
                  key={cmd.name}
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
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              autoResize()
            }}
            onCompositionStart={() => {
              composingRef.current = true
            }}
            onCompositionEnd={() => {
              composingRef.current = false
            }}
            onKeyDown={(e) => {
              // IME 在組字中(注音/拼音)按 Enter 是確認候選詞,不是送出。
              // e.nativeEvent.isComposing 是現代瀏覽器 spec;composingRef 雙保險。
              if (e.nativeEvent.isComposing || composingRef.current) return
              // Slash command popover 開時,方向鍵 / Tab / Enter / Esc 給 popover 處理
              if (showSlash) {
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setSlashIdx((i) => (i + 1) % slashMatches.length)
                  return
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setSlashIdx((i) => (i - 1 + slashMatches.length) % slashMatches.length)
                  return
                }
                if (e.key === 'Tab') {
                  e.preventDefault()
                  pickSlash(slashMatches[slashIdx])
                  return
                }
                if (e.key === 'Enter' && !e.shiftKey) {
                  // Popover 內 Enter = 執行 highlighted 命令(不是送 prompt)
                  e.preventDefault()
                  const cmd = slashMatches[slashIdx]
                  if (cmd) void executeSlashCommand(cmd.name)
                  return
                }
                if (e.key === 'Escape') {
                  e.preventDefault()
                  setText('')
                  if (textareaRef.current) textareaRef.current.value = ''
                  return
                }
              }
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
            className="scrollbar-thin max-h-[200px] resize-none bg-transparent px-1 py-1 text-sm text-fg-base placeholder:text-fg-subtle focus:outline-none disabled:cursor-not-allowed"
          />

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
          })),
        ),
      )
      .catch(() => {})
  }, [catalogLoaded, setCatalog])

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
              providers.map((p) => (
                <div key={p.id}>
                  <div className="flex items-center justify-between border-b border-bg-hover px-3 py-1.5 text-[11px] uppercase tracking-wide text-fg-subtle">
                    <span>{p.label}</span>
                    {!p.api_key_configured && (
                      <span className="text-warning">
                        {t('settings.model.apiKeyMissing')}
                      </span>
                    )}
                  </div>
                  {p.models.map((m) => {
                    const active =
                      selectedProvider === p.id && selectedModel === m.id
                    return (
                      <button
                        key={m.id}
                        type="button"
                        disabled={!p.api_key_configured}
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
              ))
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
  const error = useAgentStore((s) => s.error)
  const status = useAgentStore((s) => s.lastLoopStatus)
  if (error) {
    return <p className="mt-1 px-2 text-xs text-error">⚠ {error}</p>
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
