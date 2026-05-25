import { useEffect, useRef, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { LOCALE_LABELS, LOCALES, useTranslation, type Locale } from '../i18n'
import { useUiStore } from '../store/uiStore'
import { useTheme } from '../hooks/useTheme'
import type { ThemePref } from '../lib/theme'
import type { CustomInstructionsResponse } from '../types/events'

const selectClasses =
  'w-full max-w-xs border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] bg-claude-cream text-claude-text focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

/** 圖片 → 正方形 cover crop → JPEG data URL(對齊 Cowork resizeToJpeg)。 */
async function resizeToJpeg(
  file: File,
  edge: number,
  quality: number,
): Promise<string> {
  const bitmap = await createImageBitmap(file)
  const canvas = document.createElement('canvas')
  canvas.width = edge
  canvas.height = edge
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas 2d unavailable')
  const side = Math.min(bitmap.width, bitmap.height)
  const sx = (bitmap.width - side) / 2
  const sy = (bitmap.height - side) / 2
  ctx.drawImage(bitmap, sx, sy, side, side, 0, 0, edge, edge)
  bitmap.close()
  return canvas.toDataURL('image/jpeg', quality)
}

/** ICON / 頭像設定 — 上傳→256² JPEG→localStorage(uiStore)。顯在 sidebar user 列。 */
function AvatarSection() {
  const { t } = useTranslation()
  const avatar = useUiStore((s) => s.userAvatar)
  const setAvatar = useUiStore((s) => s.setUserAvatar)
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onPick(file: File) {
    setError(null)
    setBusy(true)
    try {
      setAvatar(await resizeToJpeg(file, 256, 0.85))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="font-medium text-claude-text text-[13px]">
        {t('settings.avatar.title')}
      </div>
      <div className="text-[12px] text-claude-textDim">
        {t('settings.avatar.hint')}
      </div>
      <div className="flex items-center gap-3 pt-1">
        <div className="h-14 w-14 shrink-0 inline-flex items-center justify-center overflow-hidden rounded-full bg-claude-orange/20 text-claude-orange">
          {avatar ? (
            <img
              src={avatar}
              alt="avatar"
              className="h-full w-full object-cover"
            />
          ) : (
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.6" />
              <path
                d="M4 20c0-4 3.6-6 8-6s8 2 8 6"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="px-3 py-1.5 rounded-md border border-claude-border text-[13px] hover:bg-claude-panel disabled:opacity-50 transition-colors"
          >
            {avatar ? t('settings.avatar.change') : t('settings.avatar.pick')}
          </button>
          {avatar && (
            <button
              type="button"
              onClick={() => setAvatar(null)}
              disabled={busy}
              className="px-3 py-1.5 rounded-md text-[13px] text-claude-textDim hover:bg-claude-panel hover:text-claude-text disabled:opacity-50 transition-colors"
            >
              {t('settings.avatar.remove')}
            </button>
          )}
        </div>
        {error && <span className="text-[12px] text-red-600">{error}</span>}
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

function AppearanceSection() {
  const { t } = useTranslation()
  const { pref, resolved, setPref } = useTheme()
  const themeWord =
    resolved === 'dark'
      ? t('settings.appearance.dark')
      : t('settings.appearance.light')
  return (
    <div className="space-y-2">
      <div className="font-medium text-claude-text text-[13px]">
        {t('settings.appearance.title')}
      </div>
      <select
        value={pref}
        onChange={(e) => setPref(e.target.value as ThemePref)}
        className={selectClasses}
      >
        <option value="system">{t('settings.appearance.system')}</option>
        <option value="light">{t('settings.appearance.light')}</option>
        <option value="dark">{t('settings.appearance.dark')}</option>
      </select>
      <div className="text-[12px] text-claude-textDim">
        {pref === 'system'
          ? t('settings.appearance.currentSystem', { theme: themeWord })
          : t('settings.appearance.current', { theme: themeWord })}
      </div>
    </div>
  )
}

function LanguageSection() {
  const { t } = useTranslation()
  const locale = useUiStore((s) => s.locale)
  const setLocale = useUiStore((s) => s.setLocale)
  return (
    <div className="space-y-2">
      <div className="font-medium text-claude-text text-[13px]">
        {t('settings.language.title')}
      </div>
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        className={selectClasses}
      >
        {LOCALES.map((l) => (
          <option key={l} value={l}>
            {LOCALE_LABELS[l]}
          </option>
        ))}
      </select>
    </div>
  )
}

/** 自訂指令(單一 user-level,對齊 Cowork user_instructions)。 */
function InstructionsSection() {
  const { t } = useTranslation()
  const [user, setUser] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    void apiFetch<CustomInstructionsResponse>('/me/custom-instructions')
      .then((me) => {
        if (alive) setUser(me.user_level ?? '')
      })
      .catch((e) => {
        if (!alive) return
        if (e instanceof ApiError && e.status === 503) setUnavailable(true)
        else setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      alive = false
    }
  }, [])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await apiFetch('/me/custom-instructions', {
        method: 'PUT',
        body: { instructions: user || null },
      })
      setSavedAt(Date.now())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (unavailable) {
    return (
      <div className="text-claude-textDim text-[13px]">
        {t('settings.instructions.dbRequired')}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="font-medium text-claude-text text-[13px]">
        {t('settings.instructions.aboutYou')}
      </div>
      <div className="text-[12px] text-claude-textDim">
        {t('settings.instructions.aboutYouHint')}
      </div>
      <textarea
        className="w-full h-28 border border-claude-border rounded-lg p-3 text-[13px] bg-white dark:bg-claude-cream text-claude-text placeholder:text-claude-textFaint focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow resize-none"
        placeholder={t('settings.instructions.aboutYouPlaceholder')}
        value={user}
        onChange={(e) => setUser(e.target.value)}
      />
      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-emerald-700 dark:text-emerald-400">
          {savedAt &&
            t('settings.instructions.saved', {
              time: new Date(savedAt).toLocaleTimeString(),
            })}
        </span>
        <button
          onClick={() => void save()}
          disabled={busy}
          className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  )
}

/**
 * 「一般」設定 — 對齊 Cowork General:頭像(ICON)+ 外觀 + 語言 + 自訂指令。
 * 原本分開的「設定」「指令」兩個 tab 合併到這裡。
 */
export function SettingsPanel() {
  return (
    <div className="p-6 space-y-6 text-[14px]">
      <AvatarSection />
      <AppearanceSection />
      <LanguageSection />
      <div className="border-t border-claude-border/60 pt-5">
        <InstructionsSection />
      </div>
    </div>
  )
}
