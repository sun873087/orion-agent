import { useEffect, useRef, useState } from 'react'
import { Folder, Keyboard, Moon, Sun, User, X } from 'lucide-react'

import { getPrefs, setPref } from '../../api/agent'
import { useTranslation } from '../../i18n'
import { useSettingsStore } from '../../store/settings'

export function GeneralSection() {
  const { t } = useTranslation()
  const [defaultWorkspace, setDefaultWorkspace] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [instructions, setInstructions] = useState('')
  const [instructionsServer, setInstructionsServer] = useState('')
  const [savingInstr, setSavingInstr] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      const p = await getPrefs()
      setDefaultWorkspace(p.default_workspace_dir || null)
      const ui = p.user_instructions ?? ''
      setInstructions(ui)
      setInstructionsServer(ui)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function pick() {
    const dir = await window.dialog.selectFolder()
    if (!dir) return
    await setPref('default_workspace_dir', dir)
    setDefaultWorkspace(dir)
  }

  async function clear() {
    await setPref('default_workspace_dir', null)
    setDefaultWorkspace(null)
  }

  async function saveInstructions() {
    setSavingInstr(true)
    try {
      const trimmed = instructions.trim()
      await setPref('user_instructions', trimmed || null)
      setInstructionsServer(trimmed)
    } finally {
      setSavingInstr(false)
    }
  }

  const instrDirty = instructions.trim() !== instructionsServer.trim()

  return (
    <div className="flex flex-col gap-6">
      <AvatarPicker />
      <ThemeToggle />
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-fg-muted">
          {t('general.instructions')}
        </label>
        <p className="text-[11px] text-fg-subtle">
          {t('general.instructionsHint')}
        </p>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={8}
          placeholder={t('general.instructionsPlaceholder')}
          className="scrollbar-thin mt-2 resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-2 text-sm focus:border-accent focus:outline-none"
        />
        <div className="mt-1 flex items-center justify-end gap-2">
          {instrDirty && (
            <button
              type="button"
              onClick={() => setInstructions(instructionsServer)}
              disabled={savingInstr}
              className="rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:opacity-40"
            >
              {t('general.discard')}
            </button>
          )}
          <button
            type="button"
            onClick={saveInstructions}
            disabled={!instrDirty || savingInstr}
            className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            {savingInstr ? '…' : t('general.save')}
          </button>
        </div>
      </div>
      <KeyboardShortcutsRow />
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-fg-muted">
          {t('general.defaultWorkspace')}
        </label>
        <p className="text-[11px] text-fg-subtle">
          {t('general.defaultWorkspaceHint')}
        </p>
        {loading && !defaultWorkspace ? (
          <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
        ) : defaultWorkspace ? (
          <div className="mt-2 flex w-fit items-center gap-2 rounded-md border border-bg-hover bg-bg-panel px-3 py-1.5">
            <button
              type="button"
              onClick={() => window.shellApi.revealInFinder(defaultWorkspace)}
              title={t('general.revealInFinder')}
              className="flex items-center gap-2 rounded hover:text-accent"
            >
              <Folder size={14} className="text-fg-muted" />
              <span className="font-mono text-xs text-fg-base underline-offset-4 hover:underline">
                {defaultWorkspace}
              </span>
            </button>
            <button
              type="button"
              onClick={pick}
              className="rounded px-2 py-0.5 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            >
              {t('general.change')}
            </button>
            <button
              type="button"
              onClick={clear}
              className="rounded p-1 text-fg-subtle hover:bg-error/20 hover:text-error"
              title={t('general.clear')}
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={pick}
            className="mt-2 flex w-fit items-center gap-2 rounded-md border border-bg-hover bg-bg-panel px-4 py-1.5 text-sm hover:bg-bg-hover"
          >
            <Folder size={14} />
            <span>{t('general.pickFolder')}</span>
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * 個人頭像上傳 — canvas resize 到 256×256 JPEG 0.85,存 zustand persist
 * (localStorage)。沒打 sidecar,純 renderer。Avatar 顯在訊息泡泡 user 側
 * + Sidebar 底部 user 列。
 */
function AvatarPicker() {
  const { t } = useTranslation()
  const avatar = useSettingsStore((s) => s.userAvatar)
  const setAvatar = useSettingsStore((s) => s.setUserAvatar)
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onPick(file: File) {
    setError(null)
    setBusy(true)
    try {
      const dataUrl = await resizeToJpeg(file, 256, 0.85)
      setAvatar(dataUrl)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-fg-muted">
        {t('general.avatar')}
      </label>
      <p className="text-[11px] text-fg-subtle">{t('general.avatarHint')}</p>
      <div className="mt-2 flex items-center gap-3">
        <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-accent/15 text-accent">
          {avatar ? (
            <img src={avatar} alt="avatar" className="h-full w-full object-cover" />
          ) : (
            <User size={28} />
          )}
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
              className="rounded-md border border-bg-hover bg-bg-panel px-3 py-1 text-xs hover:bg-bg-hover disabled:opacity-40"
            >
              {avatar ? t('general.avatarChange') : t('general.avatarPick')}
            </button>
            {avatar && (
              <button
                type="button"
                onClick={() => setAvatar(null)}
                disabled={busy}
                className="rounded-md px-3 py-1 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:opacity-40"
              >
                {t('general.avatarRemove')}
              </button>
            )}
          </div>
          {error && <p className="text-[11px] text-error">{error}</p>}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void onPick(f)
            if (inputRef.current) inputRef.current.value = ''
          }}
        />
      </div>
    </div>
  )
}

/** 主題切換 — 原本獨立的 Appearance section,併進 General 簡化導覽。 */
function ThemeToggle() {
  const { t } = useTranslation()
  const theme = useSettingsStore((s) => s.theme)
  const toggleTheme = useSettingsStore((s) => s.toggleTheme)
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-fg-muted">
        {t('general.appearance')}
      </label>
      <button
        type="button"
        onClick={toggleTheme}
        className="mt-2 flex w-fit items-center gap-3 rounded-lg border border-bg-hover bg-bg-panel px-4 py-2 text-sm hover:bg-bg-hover"
      >
        {theme === 'dark' ? <Moon size={14} /> : <Sun size={14} />}
        <span>{theme === 'dark' ? t('settings.theme.dark') : t('settings.theme.light')}</span>
        <span className="text-xs text-fg-subtle">{t('settings.theme.toggleHint')}</span>
      </button>
    </div>
  )
}

/** 鍵盤快捷鍵入口 — 點下去開全域 cheat sheet modal(也可以直接按 `?`)。
 * 放這讓不知道有快捷鍵的 user 也能發現。 */
function KeyboardShortcutsRow() {
  const { t } = useTranslation()
  const openShortcuts = useSettingsStore((s) => s.openShortcuts)
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-fg-muted">{t('general.shortcuts')}</label>
      <p className="text-[11px] text-fg-subtle">{t('general.shortcutsHint')}</p>
      <button
        type="button"
        onClick={openShortcuts}
        className="mt-2 flex w-fit items-center gap-2 rounded-md border border-bg-hover bg-bg-panel px-4 py-1.5 text-sm hover:bg-bg-hover"
      >
        <Keyboard size={14} />
        <span>{t('general.viewShortcuts')}</span>
        <kbd className="rounded border border-bg-hover bg-bg-base px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
          ?
        </kbd>
      </button>
    </div>
  )
}

/** Resize image → 正方形 cover crop → JPEG data URL。 */
async function resizeToJpeg(file: File, edge: number, quality: number): Promise<string> {
  const bitmap = await createImageBitmap(file)
  const canvas = document.createElement('canvas')
  canvas.width = edge
  canvas.height = edge
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas 2d unavailable')
  // Cover crop:取中央正方形
  const side = Math.min(bitmap.width, bitmap.height)
  const sx = (bitmap.width - side) / 2
  const sy = (bitmap.height - side) / 2
  ctx.drawImage(bitmap, sx, sy, side, side, 0, 0, edge, edge)
  bitmap.close()
  return canvas.toDataURL('image/jpeg', quality)
}
