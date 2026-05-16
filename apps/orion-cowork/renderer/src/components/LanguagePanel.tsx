import { Check, Globe, X } from 'lucide-react'

import { LOCALES, useTranslation, type Locale } from '../i18n'
import { useSettingsStore } from '../store/settings'

/** 獨立 Language 選擇器 — 與 Settings 解耦,將來易加 Profile / Shortcuts 等項目。 */
export function LanguagePanel() {
  const { t } = useTranslation()
  const open = useSettingsStore((s) => s.languagePanelOpen)
  const onClose = useSettingsStore((s) => s.closeLanguagePanel)
  const locale = useSettingsStore((s) => s.locale)
  const setLocale = useSettingsStore((s) => s.setLocale)

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-md flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="text-sm font-semibold">{t('language.title')}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            title={t('settings.close')}
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex flex-col px-2 py-2">
          {LOCALES.map((l) => {
            const active = l === locale
            return (
              <button
                key={l}
                type="button"
                onClick={() => {
                  setLocale(l)
                  onClose()
                }}
                className={`flex items-center justify-between rounded-md px-3 py-2 text-sm transition-colors ${
                  active
                    ? 'bg-accent/15 text-accent'
                    : 'text-fg-base hover:bg-bg-hover'
                }`}
              >
                <span className="flex items-center gap-2">
                  {active ? <Check size={14} /> : <Globe size={14} className="opacity-60" />}
                  <span>{t(`lang.${l}` as `lang.${Locale}`)}</span>
                </span>
                <span className="font-mono text-[10px] text-fg-subtle">{l}</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
