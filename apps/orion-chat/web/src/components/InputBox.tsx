import { useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch, apiUpload } from '../api/client'
import { useTranslation } from '../i18n'
import { useUiStore } from '../store/uiStore'
import type { ModelCatalog, UploadSummary } from '../types/events'
import type { ModelChoice } from '../lib/preferredModel'
import {
  applyMention,
  buildSendPrefix,
  buildSlashCommands,
  detectMention,
  filterMentions,
  filterSlash,
  isClientCommand,
  slashQuery,
  type ClientCommandName,
  type SkillRef,
  type SlashCommand,
} from '../lib/inputCommands'
import { ModelPicker } from './ModelPicker'

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => {
      // data:audio/webm;base64,XXXX → 後端只要 base64 本體,去掉 data: 前綴
      resolve((reader.result as string).split(',')[1] ?? '')
    }
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}

interface Props {
  disabled: boolean
  onSend: (text: string, attachments: UploadSummary[]) => void
  onAbort: () => void
  /** 模型選擇器移進輸入框 — 沒有可選模型(無 session/draft)時不顯示。 */
  modelValue: ModelChoice | null
  catalog: ModelCatalog | null
  onModelChange: (choice: ModelChoice) => void
  /** slash `@file:` 候選來源 + client 指令的 active session;draft 時為 null。 */
  sessionId: string | null
  /** `/compact` `/plan` `/context` `/schedule` 等 client 指令交給 ChatView 執行。 */
  onClientCommand: (name: ClientCommandName) => void
}

export function InputBox({
  disabled,
  onSend,
  onAbort,
  modelValue,
  catalog,
  onModelChange,
  sessionId,
  onClientCommand,
}: Props) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [cursor, setCursor] = useState(0)
  const [pendingFiles, setPendingFiles] = useState<UploadSummary[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const prevDisabledRef = useRef(disabled)
  const locale = useUiStore((s) => s.locale)

  // slash / mention autocomplete
  const [skills, setSkills] = useState<SkillRef[]>([])
  const [wsFiles, setWsFiles] = useState<string[]>([])
  const [acIdx, setAcIdx] = useState(0)
  // Esc 暫時關閉 popover(直到下次編輯);derived open 狀態才不會馬上又彈回
  const [acDismissed, setAcDismissed] = useState(false)

  useEffect(() => {
    let alive = true
    void apiFetch<{ name: string; description: string }[]>('/skills')
      .then((rows) => {
        if (alive) setSkills(rows.map((r) => ({ name: r.name, description: r.description })))
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (!sessionId) {
      setWsFiles([])
      return
    }
    let alive = true
    void apiFetch<{ name: string }[]>(`/sessions/${sessionId}/files`)
      .then((rows) => {
        if (alive) setWsFiles(rows.map((r) => r.name))
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [sessionId])

  // ── derived popover 狀態(text + cursor 推導) ──
  const slashQ = slashQuery(text)
  const slashCommands = useMemo(
    () => buildSlashCommands(skills, !!sessionId),
    [skills, sessionId],
  )
  const slashMatches =
    slashQ !== null ? filterSlash(slashCommands, slashQ) : []
  const showSlash = !acDismissed && slashQ !== null && slashMatches.length > 0

  const mentionCtx = !acDismissed && !showSlash ? detectMention(text, cursor) : null
  const mentionMatches = mentionCtx
    ? filterMentions(mentionCtx, skills, wsFiles)
    : []
  const showMention = !!mentionCtx && mentionMatches.length > 0
  const acLen = showSlash
    ? slashMatches.length
    : showMention
      ? mentionMatches.length
      : 0
  const acOpen = showSlash || showMention
  const idx = acLen > 0 ? Math.min(acIdx, acLen - 1) : 0

  function pickSlash(cmd: SlashCommand) {
    if (cmd.kind === 'client' && isClientCommand(cmd.name)) {
      onClientCommand(cmd.name)
      setText('')
      setAcDismissed(true)
    } else {
      // skill → 換成 @skill: token,讓送出時自動加 prompt 前綴
      const next = `@skill:${cmd.name.slice(1)} `
      setText(next)
      setCursor(next.length)
      setAcDismissed(true)
    }
    requestAnimationFrame(() => taRef.current?.focus())
  }

  function pickMention(item: (typeof mentionMatches)[number]) {
    if (!mentionCtx) return
    const r = applyMention(text, mentionCtx, item)
    setText(r.text)
    setCursor(r.cursor)
    setAcDismissed(true)
    requestAnimationFrame(() => {
      const ta = taRef.current
      if (ta) {
        ta.focus()
        ta.setSelectionRange(r.cursor, r.cursor)
      }
    })
  }

  function acConfirm() {
    if (showSlash) pickSlash(slashMatches[idx]!)
    else if (showMention) pickMention(mentionMatches[idx]!)
  }

  // STT — 麥克風錄音 → /voice/stt 轉錄,結果接到 textarea 後面。
  const [sttAvailable, setSttAvailable] = useState(false)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const recStartRef = useRef(0)

  useEffect(() => {
    let alive = true
    void apiFetch<{ stt_available: boolean }>('/voice/status')
      .then((r) => {
        if (alive) setSttAvailable(r.stt_available)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  // 訊息送出 → inFlight=true → textarea 被 disable,瀏覽器自動 blur。
  // 回應結束 disabled 變回 false 時把 focus 拉回來。
  useEffect(() => {
    if (prevDisabledRef.current && !disabled) {
      taRef.current?.focus()
    }
    prevDisabledRef.current = disabled
  }, [disabled])

  async function uploadFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setError(null)
    setUploading(true)
    try {
      const list: UploadSummary[] = []
      for (const f of Array.from(files)) {
        const fd = new FormData()
        fd.append('file', f)
        const u = await apiUpload<UploadSummary>('/uploads', fd)
        list.push(u)
      }
      setPendingFiles((prev) => [...prev, ...list])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }

  function send() {
    const raw = text.trim()
    if (!raw && pendingFiles.length === 0) return
    // @skill: / @file: 引用 → 加 prompt 前綴讓 LLM 知道要載 skill / 讀檔
    const prefix = buildSendPrefix(raw)
    const finalText = prefix ? `${prefix}\n\n${raw}` : raw
    onSend(finalText, pendingFiles)
    setText('')
    setCursor(0)
    setPendingFiles([])
    if (fileRef.current) fileRef.current.value = ''
    if (taRef.current) taRef.current.style.height = 'auto'
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // popover 開著時,方向鍵 / Enter / Tab / Esc 先給 autocomplete
    if (acOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setAcIdx((i) => (i + 1) % acLen)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setAcIdx((i) => (i - 1 + acLen) % acLen)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setAcDismissed(true)
        return
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault()
        acConfirm()
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault()
      send()
    }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      send()
    }
  }

  function autoGrow(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setText(e.target.value)
    setCursor(e.target.selectionStart ?? e.target.value.length)
    setAcDismissed(false) // 重新編輯 → 解除 Esc 暫關
    setAcIdx(0)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 240)}px`
  }

  function syncCursor(e: React.SyntheticEvent<HTMLTextAreaElement>) {
    setCursor(e.currentTarget.selectionStart ?? 0)
  }

  function removeFile(id: string) {
    setPendingFiles((prev) => prev.filter((f) => f.upload_id !== id))
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop()
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      recStartRef.current = Date.now()
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      rec.onstop = () => {
        // 停止後一律放掉麥克風(否則瀏覽器分頁會一直顯示錄音中)
        stream.getTracks().forEach((track) => track.stop())
        void transcribe()
      }
      recorderRef.current = rec
      rec.start()
      setRecording(true)
      setError(null)
    } catch {
      setError('Microphone access denied')
    }
  }

  async function transcribe() {
    setRecording(false)
    const rec = recorderRef.current
    const blob = new Blob(chunksRef.current, {
      type: rec?.mimeType || 'audio/webm',
    })
    // <1s 的點擊誤觸不送(後端也會擋,省一趟 round-trip)
    if (blob.size < 1024) return
    const durationSeconds = (Date.now() - recStartRef.current) / 1000
    setTranscribing(true)
    try {
      const audioBase64 = await blobToBase64(blob)
      const res = await apiFetch<{ text: string }>('/voice/stt', {
        method: 'POST',
        body: {
          audio_base64: audioBase64,
          mime_type: blob.type,
          locale,
          duration_seconds: durationSeconds,
        },
      })
      if (res.text) {
        setText((prev) => (prev ? `${prev} ${res.text}` : res.text))
        taRef.current?.focus()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTranscribing(false)
    }
  }

  // 阻止 textarea / 任何子元素 native drop(否則拖檔會被瀏覽器導航 / 變字串塞進 textarea = GG)
  const stop = (e: React.DragEvent | React.SyntheticEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  return (
    <div
      className="px-4 pb-4 pt-2"
      onDragEnter={(e) => {
        stop(e)
        setDragActive(true)
      }}
      onDragOver={stop}
      onDragLeave={(e) => {
        // 只在離開最外層 wrapper 時關 highlight,進子元素不關
        if (e.currentTarget === e.target) setDragActive(false)
      }}
      onDrop={(e) => {
        stop(e)
        setDragActive(false)
        void uploadFiles(e.dataTransfer.files)
      }}
    >
      <div className="max-w-3xl mx-auto">
        {error && (
          <div className="mb-2 text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-1.5 rounded-md">
            {error}
          </div>
        )}

        <div
          className={`relative rounded-2xl bg-white dark:bg-claude-panel shadow-input dark:shadow-none dark:ring-1 dark:ring-claude-border transition-shadow ${
            dragActive ? 'ring-2 ring-claude-orange/40' : ''
          }`}
        >
          {acOpen && (
            <div className="absolute left-2 right-2 bottom-full mb-2 z-30 max-h-72 overflow-y-auto rounded-xl bg-white dark:bg-claude-panel ring-1 ring-claude-border shadow-modal py-1.5 animate-fade-in">
              {showSlash
                ? slashMatches.map((cmd, i) => (
                    <button
                      key={cmd.name}
                      type="button"
                      className={`w-full text-left px-3 py-1.5 flex items-center gap-2 ${
                        i === idx
                          ? 'bg-claude-orangeSoft/40 text-claude-text'
                          : 'text-claude-text hover:bg-claude-borderSoft/60'
                      }`}
                      onMouseDown={(e) => {
                        e.preventDefault()
                        pickSlash(cmd)
                      }}
                      onMouseEnter={() => setAcIdx(i)}
                    >
                      <span className="font-mono text-[13px]">{cmd.name}</span>
                      <span className="text-[12px] text-claude-textDim truncate">
                        {cmd.kind === 'client' && cmd.descKey
                          ? t(cmd.descKey)
                          : (cmd.desc ?? t('chat.slash.skill'))}
                      </span>
                    </button>
                  ))
                : mentionMatches.map((item, i) => (
                    <button
                      key={`${item.kind}:${item.value}`}
                      type="button"
                      className={`w-full text-left px-3 py-1.5 flex items-center gap-2 ${
                        i === idx
                          ? 'bg-claude-orangeSoft/40 text-claude-text'
                          : 'text-claude-text hover:bg-claude-borderSoft/60'
                      }`}
                      onMouseDown={(e) => {
                        e.preventDefault()
                        pickMention(item)
                      }}
                      onMouseEnter={() => setAcIdx(i)}
                    >
                      <span className="text-[11px] uppercase tracking-wide text-claude-textFaint w-9 shrink-0">
                        {item.kind === 'skill' ? 'skill' : 'file'}
                      </span>
                      <span className="text-[13px] truncate">{item.label}</span>
                      {item.detail && (
                        <span className="text-[12px] text-claude-textDim truncate">
                          {item.detail}
                        </span>
                      )}
                    </button>
                  ))}
            </div>
          )}
          {pendingFiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-3">
              {pendingFiles.map((f) => (
                <span
                  key={f.upload_id}
                  className="inline-flex items-center gap-1.5 text-[12px] bg-claude-panel border border-claude-border rounded-full pl-2.5 pr-1 py-1"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 16 16"
                    fill="none"
                    className="text-claude-textDim"
                  >
                    <path
                      d="M10 3v6.5a2.5 2.5 0 11-5 0V4a1.5 1.5 0 113 0v5.5a.5.5 0 11-1 0V4.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                  {f.filename}
                  <span className="text-claude-textFaint">
                    {Math.round(f.size / 1024)}KB
                  </span>
                  <button
                    className="ml-1 h-4 w-4 inline-flex items-center justify-center rounded-full text-claude-textFaint hover:bg-claude-border hover:text-claude-text"
                    onClick={() => removeFile(f.upload_id)}
                    aria-label="remove"
                  >
                    <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                      <path
                        d="M2 2l4 4M6 2l-4 4"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                </span>
              ))}
            </div>
          )}

          <textarea
            ref={taRef}
            className="w-full resize-none px-4 pt-3 pb-1 text-[15px] leading-relaxed placeholder:text-claude-textFaint focus:outline-none"
            placeholder="Reply to Orion…"
            rows={1}
            value={text}
            onChange={autoGrow}
            onKeyDown={onKeyDown}
            onClick={syncCursor}
            onKeyUp={syncCursor}
            onSelect={syncCursor}
            // textarea native drop 預設會把檔案 URL / 路徑塞成 text — 必須擋掉,讓外層 wrapper 處理
            onDragOver={stop}
            onDrop={(e) => {
              stop(e)
              setDragActive(false)
              void uploadFiles(e.dataTransfer.files)
            }}
            disabled={disabled}
            style={{ maxHeight: 240 }}
          />

          <div className="flex items-center gap-1 px-2.5 pb-2.5">
            <button
              className="p-2 rounded-lg text-claude-textDim hover:bg-claude-panel hover:text-claude-text disabled:opacity-50 transition-colors"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              title="Attach file"
            >
              {uploading ? (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <circle
                    cx="8"
                    cy="8"
                    r="6"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeOpacity="0.3"
                  />
                  <path
                    d="M14 8a6 6 0 00-6-6"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    className="origin-center"
                    style={{
                      animation: 'spin 1s linear infinite',
                      transformOrigin: 'center',
                    }}
                  />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M11.5 8L8.5 11a2 2 0 11-2.83-2.83l4-4a3.5 3.5 0 014.95 4.95l-5.62 5.62a5 5 0 01-7.07-7.07l4-4"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => void uploadFiles(e.target.files)}
            />

            <div className="ml-auto flex items-center gap-1.5">
              {modelValue && (
                <ModelPicker
                  value={modelValue}
                  catalog={catalog}
                  onChange={onModelChange}
                  direction="up"
                  disabled={disabled}
                />
              )}
              {sttAvailable && (
                <button
                  className={`p-2 rounded-lg transition-colors disabled:opacity-50 ${
                    recording
                      ? 'text-red-600 bg-red-50 dark:bg-red-950/40 animate-pulse'
                      : 'text-claude-textDim hover:bg-claude-panel hover:text-claude-text'
                  }`}
                  onClick={() => void toggleRecording()}
                  disabled={disabled || transcribing}
                  title={recording ? 'Stop recording' : 'Dictate (speech-to-text)'}
                  aria-label="dictate"
                >
                  {transcribing ? (
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <circle
                        cx="8"
                        cy="8"
                        r="6"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeOpacity="0.3"
                      />
                      <path
                        d="M14 8a6 6 0 00-6-6"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        style={{
                          animation: 'spin 1s linear infinite',
                          transformOrigin: 'center',
                        }}
                      />
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <rect
                        x="6"
                        y="2"
                        width="4"
                        height="7"
                        rx="2"
                        stroke="currentColor"
                        strokeWidth="1.4"
                      />
                      <path
                        d="M3.5 7.5a4.5 4.5 0 009 0M8 12v2"
                        stroke="currentColor"
                        strokeWidth="1.4"
                        strokeLinecap="round"
                      />
                    </svg>
                  )}
                </button>
              )}
              {disabled && (
                <button
                  className="px-3 py-1.5 text-[13px] text-claude-textDim hover:text-red-600 transition-colors"
                  onClick={onAbort}
                >
                  Stop
                </button>
              )}
              <button
                className="h-8 w-8 inline-flex items-center justify-center rounded-lg bg-claude-orange text-white hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint disabled:cursor-not-allowed transition-colors"
                onClick={send}
                disabled={
                  disabled || (!text.trim() && pendingFiles.length === 0)
                }
                title="Send (Enter)"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M8 13V3M3 8l5-5 5 5"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <div className="mt-1.5 px-1 text-[11px] text-claude-textFaint text-center">
          Enter to send · Shift+Enter for newline · drop files to attach
        </div>
      </div>
    </div>
  )
}
