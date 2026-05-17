import { useEffect, useState } from 'react'
import { AlertCircle, Check, Layers, Mic } from 'lucide-react'

import {
  fetchModels,
  getSttStatus,
  type SttCatalog,
} from '../../api/agent'
import { useTranslation } from '../../i18n'
import {
  useSettingsStore,
  type OpenAiSttModel,
  type SttProvider,
} from '../../store/settings'

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
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-medium text-fg-muted">{t('settings.model.chatHeading')}</h3>
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
      <SttPicker />
      <AutoCompactPicker />
    </div>
  )
}

/** 對話壓縮設定 — context 用量超過 threshold 時自動摘要前段。可關閉 + 手動 /compact 隨時用。 */
function AutoCompactPicker() {
  const enabled = useSettingsStore((s) => s.autoCompactEnabled)
  const setEnabled = useSettingsStore((s) => s.setAutoCompactEnabled)
  const threshold = useSettingsStore((s) => s.autoCompactThreshold)
  const setThreshold = useSettingsStore((s) => s.setAutoCompactThreshold)
  const pct = Math.round(threshold * 100)

  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Layers size={14} />
        對話壓縮
      </h3>
      <p className="text-[11px] text-fg-subtle">
        當對話累積到模型 context window 的設定比例時,自動把前半段摘要成一張卡,釋出 token 額度。
        也可以隨時在輸入框打 <code className="rounded bg-bg-hover px-1 font-mono text-[10px]">/compact</code> 手動觸發。
      </p>
      <label className="mt-1 flex w-fit cursor-pointer items-center gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-1.5 text-sm hover:border-accent/40 hover:bg-bg-hover">
        <input
          type="checkbox"
          className="accent-accent"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <span>啟用自動壓縮</span>
      </label>
      <div className={`mt-1 flex flex-col gap-1 ${enabled ? '' : 'opacity-40'}`}>
        <label className="text-[11px] font-medium text-fg-muted">
          觸發閾值:<span className="font-mono text-fg-base">{pct}%</span>
        </label>
        <input
          type="range"
          min={50}
          max={95}
          step={5}
          value={pct}
          disabled={!enabled}
          onChange={(e) => setThreshold(Number(e.target.value) / 100)}
          className="w-64 accent-accent disabled:cursor-not-allowed"
        />
        <div className="flex w-64 justify-between text-[10px] text-fg-subtle">
          <span>50%</span>
          <span>80%(預設)</span>
          <span>95%</span>
        </div>
      </div>
    </div>
  )
}

/** STT (speech-to-text) provider + model 選擇 — catalog 來自 orion-model
 *  經 sidecar stt.status RPC。本來放 General,移過來跟 chat model 同 section,
 *  因為兩者都是 "選 model"。 */
function SttPicker() {
  const { t } = useTranslation()
  const provider = useSettingsStore((s) => s.sttProvider)
  const setProvider = useSettingsStore((s) => s.setSttProvider)
  const openaiModel = useSettingsStore((s) => s.openaiSttModel)
  const setOpenaiModel = useSettingsStore((s) => s.setOpenaiSttModel)
  const [catalog, setCatalog] = useState<SttCatalog | null>(null)

  useEffect(() => {
    getSttStatus().then(setCatalog).catch(() => setCatalog(null))
  }, [])

  const ENV_HINT: Record<string, string> = {
    openai: 'OPENAI_API_KEY',
    google: 'GOOGLE_STT_API_KEY',
  }

  const opts: { value: SttProvider; available: boolean; envHint: string; label: string }[] = [
    { value: 'off', available: true, envHint: '', label: t('settings.stt.off') },
    ...(catalog?.providers ?? []).map((p) => ({
      value: p.id as SttProvider,
      available: p.api_key_configured,
      envHint: ENV_HINT[p.id] ?? '',
      label: p.label,
    })),
  ]

  const openaiEntry = catalog?.providers.find((p) => p.id === 'openai')
  const openaiModels = openaiEntry?.models ?? []

  function modelLabel(m: {
    id: string
    label: string
    pricing_per_minute_usd?: number
    recommended?: boolean
  }): string {
    const price = m.pricing_per_minute_usd ? ` · $${m.pricing_per_minute_usd}/min` : ''
    const rec = m.recommended ? ` (${t('settings.stt.recommended')})` : ''
    return `${m.label}${price}${rec}`
  }

  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Mic size={14} />
        {t('settings.stt.heading')}
      </h3>
      <p className="text-[11px] text-fg-subtle">{t('settings.stt.hint')}</p>
      <div className="mt-1 flex flex-col gap-1.5">
        {opts.map((o) => {
          const active = provider === o.value
          const disabled = !o.available
          return (
            <label
              key={o.value}
              className={`flex w-fit items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                active
                  ? 'border-accent bg-accent/10 text-fg-base'
                  : 'border-bg-hover bg-bg-panel text-fg-base hover:border-accent/40 hover:bg-bg-hover'
              } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
            >
              <input
                type="radio"
                className="accent-accent"
                checked={active}
                disabled={disabled}
                onChange={() => setProvider(o.value)}
              />
              <span>{o.label}</span>
              {disabled && o.envHint && (
                <span className="font-mono text-[10px] text-fg-subtle">
                  ({t('settings.stt.missingKey', { env: o.envHint })})
                </span>
              )}
            </label>
          )
        })}
      </div>
      {provider === 'openai' && openaiEntry?.api_key_configured && openaiModels.length > 1 && (
        <div className="ml-6 mt-1 flex flex-col gap-1">
          <label className="text-[11px] font-medium text-fg-muted">
            {t('settings.stt.openaiModel')}
          </label>
          <select
            value={openaiModel}
            onChange={(e) => setOpenaiModel(e.target.value as OpenAiSttModel)}
            className="w-fit rounded-md border border-bg-hover bg-bg-input px-2 py-1 text-xs focus:border-accent focus:outline-none"
          >
            {openaiModels.map((m) => (
              <option key={m.id} value={m.id}>
                {modelLabel(m)}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}
