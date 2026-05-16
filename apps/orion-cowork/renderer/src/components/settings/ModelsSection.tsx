import { useEffect } from 'react'
import { AlertCircle, Check } from 'lucide-react'

import { fetchModels } from '../../api/agent'
import { useTranslation } from '../../i18n'
import { useSettingsStore } from '../../store/settings'

export function ModelsSection() {
  const { t } = useTranslation()
  const providers = useSettingsStore((s) => s.providers)
  const catalogLoaded = useSettingsStore((s) => s.catalogLoaded)
  const setCatalog = useSettingsStore((s) => s.setCatalog)
  const selectedProvider = useSettingsStore((s) => s.selectedProvider)
  const selectedModel = useSettingsStore((s) => s.selectedModel)
  const setSelectedModel = useSettingsStore((s) => s.setSelectedModel)

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

  if (!catalogLoaded) {
    return <div className="text-sm text-fg-muted">{t('settings.model.loading')}</div>
  }
  if (providers.length === 0) {
    return <div className="text-sm text-error">{t('settings.model.failed')}</div>
  }

  return (
    <div className="flex flex-col gap-3">
      {providers.map((p) => (
        <div key={p.id} className="rounded-lg border border-bg-hover bg-bg-panel">
          <div className="flex items-center justify-between border-b border-bg-hover px-3 py-2">
            <span className="text-sm font-medium">{p.label}</span>
            {p.api_key_configured ? (
              <span className="flex items-center gap-1 text-xs text-success">
                <Check size={12} /> {t('settings.model.apiKeySet')}
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs text-warning">
                <AlertCircle size={12} /> {t('settings.model.apiKeyMissing')}
              </span>
            )}
          </div>
          <div className="flex flex-col">
            {p.models.map((m) => {
              const active = selectedProvider === p.id && selectedModel === m.id
              return (
                <button
                  key={m.id}
                  type="button"
                  disabled={!p.api_key_configured}
                  onClick={() => setSelectedModel(p.id, m.id)}
                  className={`flex items-center justify-between px-3 py-2 text-left text-sm transition-colors ${
                    active ? 'bg-accent/15 text-accent' : 'text-fg-base hover:bg-bg-hover'
                  } disabled:cursor-not-allowed disabled:opacity-40`}
                >
                  <span className="flex items-center gap-2">
                    {active && <Check size={12} />}
                    <span>{m.label}</span>
                    {m.supports_reasoning && (
                      <span className="rounded bg-bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                        {t('settings.model.reasoning')}
                      </span>
                    )}
                  </span>
                  <span className="font-mono text-[10px] text-fg-subtle">{m.id}</span>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
