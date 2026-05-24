import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { LOCALE_LABELS, LOCALES, useTranslation, type Locale } from '../i18n'
import { useUiStore } from '../store/uiStore'
import { useTheme } from '../hooks/useTheme'
import type { ThemePref } from '../lib/theme'

const selectClasses =
  'w-full max-w-xs border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] bg-claude-cream text-claude-text focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

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

export function SettingsPanel() {
  const { t } = useTranslation()
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [unavailable, setUnavailable] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    setError(null)
    try {
      const all = await apiFetch<Record<string, unknown>>('/me/settings')
      setSettings(all || {})
      setUnavailable(false)
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        setUnavailable(true)
      } else {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function setKey() {
    if (!newKey) return
    setBusy(true)
    setError(null)
    try {
      let parsed: unknown
      try {
        parsed = JSON.parse(newValue)
      } catch {
        parsed = newValue
      }
      await apiFetch(`/me/settings/${encodeURIComponent(newKey)}`, {
        method: 'PUT',
        body: { value: parsed },
      })
      setNewKey('')
      setNewValue('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function deleteKey(key: string) {
    if (!confirm(t('settings.deleteConfirm', { key }))) return
    setBusy(true)
    try {
      await apiFetch(`/me/settings/${encodeURIComponent(key)}`, {
        method: 'DELETE',
      })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (unavailable) {
    return (
      <div className="p-6 space-y-5 text-[14px]">
        <AppearanceSection />
        <LanguageSection />
        <div className="pt-2 border-t border-claude-border/60 text-claude-textDim">
          {t('settings.serverRequires')}
        </div>
      </div>
    )
  }

  const inputClasses =
    'w-full border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] font-mono bg-claude-cream text-claude-text focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

  return (
    <div className="p-6 space-y-5 text-[14px]">
      <AppearanceSection />
      <LanguageSection />

      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      <div className="space-y-2 pt-2 border-t border-claude-border/60">
        <div className="font-medium text-claude-text text-[13px]">
          {t('settings.storedValues')}
        </div>
        {Object.keys(settings).length === 0 ? (
          <div className="text-[13px] text-claude-textFaint italic">
            {t('settings.noSettings')}
          </div>
        ) : (
          <div className="space-y-1.5">
            {Object.entries(settings).map(([key, value]) => (
              <div
                key={key}
                className="group flex items-start gap-2 p-2.5 rounded-md bg-white dark:bg-claude-panel border border-claude-borderSoft"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-[12px] font-medium text-claude-text">
                    {key}
                  </div>
                  <pre className="text-[12px] text-claude-textDim font-mono whitespace-pre-wrap break-all mt-0.5">
                    {JSON.stringify(value)}
                  </pre>
                </div>
                <button
                  onClick={() => void deleteKey(key)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-claude-textFaint hover:text-red-600 transition"
                  aria-label="delete"
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path
                      d="M4 4l8 8M12 4l-8 8"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2 pt-2 border-t border-claude-border/60">
        <div className="font-medium text-claude-text text-[13px]">
          {t('settings.addOrUpdate')}
        </div>
        <input
          className={inputClasses}
          placeholder={t('settings.keyPlaceholder')}
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
        />
        <input
          className={inputClasses}
          placeholder={t('settings.valuePlaceholder')}
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
        />
        <button
          onClick={() => void setKey()}
          disabled={busy || !newKey}
          className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  )
}
