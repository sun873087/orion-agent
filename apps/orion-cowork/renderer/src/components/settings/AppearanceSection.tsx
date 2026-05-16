import { Moon, Sun } from 'lucide-react'

import { useTranslation } from '../../i18n'
import { useSettingsStore } from '../../store/settings'

export function AppearanceSection() {
  const { t } = useTranslation()
  const theme = useSettingsStore((s) => s.theme)
  const toggleTheme = useSettingsStore((s) => s.toggleTheme)

  return (
    <div className="flex flex-col gap-4">
      <button
        type="button"
        onClick={toggleTheme}
        className="flex w-fit items-center gap-3 rounded-lg border border-bg-hover bg-bg-panel px-4 py-2 text-sm hover:bg-bg-hover"
      >
        {theme === 'dark' ? <Moon size={14} /> : <Sun size={14} />}
        <span>{theme === 'dark' ? t('settings.theme.dark') : t('settings.theme.light')}</span>
        <span className="text-xs text-fg-subtle">{t('settings.theme.toggleHint')}</span>
      </button>
    </div>
  )
}
