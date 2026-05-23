import { useEffect, useState } from 'react'
import { AlertCircle, Check, Layers, Mic, Sparkles } from 'lucide-react'

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
            via_proxy: p.via_proxy,
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
            {p.api_key_configured && p.via_proxy ? (
              <span
                className="flex items-center gap-1 text-xs text-warning"
                title={t('settings.model.viaProxyHint')}
              >
                <AlertCircle size={12} /> {t('settings.model.viaProxy')}
              </span>
            ) : p.api_key_configured ? (
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
      <TtsPicker />
      <AutoCompactPicker />
      <FollowUpsPicker />
      <ConcurrentLimitPicker />
      <BudgetPicker />
    </div>
  )
}

/** TTS 設定— 預設 Web Speech API(免費、系統聲音),也可切 OpenAI cloud。 */
function TtsPicker() {
  const provider = useSettingsStore((s) => s.ttsProvider)
  const setProvider = useSettingsStore((s) => s.setTtsProvider)
  const model = useSettingsStore((s) => s.ttsModel)
  const setModel = useSettingsStore((s) => s.setTtsModel)
  const voice = useSettingsStore((s) => s.ttsVoice)
  const setVoice = useSettingsStore((s) => s.setTtsVoice)
  const speed = useSettingsStore((s) => s.ttsSpeed)
  const setSpeed = useSettingsStore((s) => s.setTtsSpeed)
  const autoplay = useSettingsStore((s) => s.ttsAutoplay)
  const setAutoplay = useSettingsStore((s) => s.setTtsAutoplay)
  const VOICES: Array<{ id: 'alloy' | 'echo' | 'fable' | 'nova' | 'onyx' | 'shimmer'; label: string }> = [
    { id: 'alloy', label: 'Alloy(中性)' },
    { id: 'echo', label: 'Echo(男聲)' },
    { id: 'fable', label: 'Fable(英倫)' },
    { id: 'nova', label: 'Nova(女聲,推薦)' },
    { id: 'onyx', label: 'Onyx(低沉男聲)' },
    { id: 'shimmer', label: 'Shimmer(柔和女聲)' },
  ]
  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Layers size={14} />
        TTS(念出 AI 回應)
      </h3>
      <p className="text-[11px] text-fg-subtle">
        Assistant 訊息下方有 🔊 按鈕,點下去念出該則回應。Web Speech 用系統聲音免費;
        OpenAI 走 cloud /audio/speech 較自然但每百萬字 ${'{'}15{'}'} 美金。
      </p>
      <div className="mt-1 flex flex-col gap-1">
        <label className="text-[11px] font-medium text-fg-muted">Provider</label>
        <div className="flex gap-2">
          {([
            { value: 'off' as const, label: '停用' },
            { value: 'web' as const, label: 'Web Speech(免費)' },
            { value: 'openai' as const, label: 'OpenAI(付費)' },
          ]).map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setProvider(opt.value)}
              className={`rounded-md border px-3 py-1 text-xs ${
                provider === opt.value
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-bg-hover bg-bg-panel text-fg-muted hover:border-accent/40'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      {provider === 'openai' && (
        <>
          <div className="mt-1 flex flex-col gap-1">
            <label className="text-[11px] font-medium text-fg-muted">Model</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value as 'tts-1' | 'tts-1-hd')}
              className="w-64 rounded-md border border-bg-hover bg-bg-input px-2 py-1 text-xs focus:border-accent focus:outline-none"
            >
              <option value="tts-1">tts-1(標準 · $15/1M 字)</option>
              <option value="tts-1-hd">tts-1-hd(高品質 · $30/1M 字)</option>
            </select>
          </div>
          <div className="mt-1 flex flex-col gap-1">
            <label className="text-[11px] font-medium text-fg-muted">Voice</label>
            <select
              value={voice}
              onChange={(e) =>
                setVoice(e.target.value as 'alloy' | 'echo' | 'fable' | 'nova' | 'onyx' | 'shimmer')
              }
              className="w-64 rounded-md border border-bg-hover bg-bg-input px-2 py-1 text-xs focus:border-accent focus:outline-none"
            >
              {VOICES.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>
        </>
      )}
      {provider !== 'off' && (
        <div className="mt-1 flex flex-col gap-1">
          <label className="text-[11px] font-medium text-fg-muted">
            播放速度:<span className="font-mono text-fg-base">{speed.toFixed(2)}x</span>
          </label>
          <input
            type="range"
            min={0.5}
            max={2.0}
            step={0.05}
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
            className="w-64 accent-accent"
          />
          <div className="flex w-64 justify-between text-[10px] text-fg-subtle">
            <span>0.5x</span>
            <span>1.0x(預設)</span>
            <span>2.0x</span>
          </div>
        </div>
      )}
      {provider !== 'off' && (
        <label className="mt-1 flex w-fit cursor-pointer items-center gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-1.5 text-sm hover:border-accent/40 hover:bg-bg-hover">
          <input
            type="checkbox"
            className="accent-accent"
            checked={autoplay}
            onChange={(e) => setAutoplay(e.target.checked)}
          />
          <span>每則 AI 回應結束後自動念</span>
        </label>
      )}
    </div>
  )
}

/** 預設 budget cap— 新 session 累積成本超過自動 abort + 顯 banner。 */
function BudgetPicker() {
  const value = useSettingsStore((s) => s.defaultBudgetUsd)
  const setValue = useSettingsStore((s) => s.setDefaultBudgetUsd)
  // 預設選項 + custom 文字框
  const PRESETS = [0, 0.5, 1, 5, 10]
  const isPreset = PRESETS.includes(value)
  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Layers size={14} />
        Cost budget(USD / session)
      </h3>
      <p className="text-[11px] text-fg-subtle">
        新開的 session 預設累積成本上限。Loop / Agent / autonomous workflow 跑久了
        會燒錢,設個 cap 超過自動 abort 並提醒。0 = 不限。Per-session 可在
        右側面板各別調整。
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setValue(p)}
            className={`rounded-md border px-3 py-1 text-xs ${
              value === p
                ? 'border-accent bg-accent/10 text-accent'
                : 'border-bg-hover bg-bg-panel text-fg-muted hover:border-accent/40'
            }`}
          >
            {p === 0 ? '不限' : `$${p.toFixed(2)}`}
          </button>
        ))}
        <div className="flex items-center gap-1">
          <span className="text-[11px] text-fg-subtle">$</span>
          <input
            type="number"
            min={0}
            step={0.01}
            value={isPreset ? '' : value}
            placeholder="自訂"
            onChange={(e) => {
              const v = parseFloat(e.target.value)
              setValue(Number.isFinite(v) ? v : 0)
            }}
            className="w-20 rounded-md border border-bg-hover bg-bg-input px-2 py-1 text-xs focus:border-accent focus:outline-none"
          />
        </div>
      </div>
    </div>
  )
}

/** 同時 in-flight conversation 上限— 避免一次跑 N 個 session 推爆 cost。 */
function ConcurrentLimitPicker() {
  const max = useSettingsStore((s) => s.maxConcurrentSessions)
  const setMax = useSettingsStore((s) => s.setMaxConcurrentSessions)
  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Layers size={14} />
        並發對話上限
      </h3>
      <p className="text-[11px] text-fg-subtle">
        同時可以有幾個 conversation 在背景跑 LLM。切到另一個 session 時舊的繼續跑,
        sidebar 顯轉圈圈;超過上限要等其中一個跑完才能開新。
      </p>
      <div className="mt-1 flex flex-col gap-1">
        <label className="text-[11px] font-medium text-fg-muted">
          上限:<span className="font-mono text-fg-base">{max}</span>
        </label>
        <input
          type="range"
          min={1}
          max={20}
          step={1}
          value={max}
          onChange={(e) => setMax(Number(e.target.value))}
          className="w-64 accent-accent"
        />
        <div className="flex w-64 justify-between text-[10px] text-fg-subtle">
          <span>1</span>
          <span>5(預設)</span>
          <span>20</span>
        </div>
      </div>
    </div>
  )
}

/** 對話壓縮設定 — context 用量超過 threshold 時自動摘要前段。可關閉 + 手動 /compact 隨時用。 */
function AutoCompactPicker() {
  const enabled = useSettingsStore((s) => s.autoCompactEnabled)
  const setEnabled = useSettingsStore((s) => s.setAutoCompactEnabled)
  const threshold = useSettingsStore((s) => s.autoCompactThreshold)
  const setThreshold = useSettingsStore((s) => s.setAutoCompactThreshold)
  const summaryProvider = useSettingsStore((s) => s.compactSummaryProvider)
  const summaryModel = useSettingsStore((s) => s.compactSummaryModel)
  const setSummary = useSettingsStore((s) => s.setCompactSummary)
  const providers = useSettingsStore((s) => s.providers)
  const pct = Math.round(threshold * 100)
  const summaryValue = summaryProvider && summaryModel ? `${summaryProvider}/${summaryModel}` : ''

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
      <div className="mt-2 flex flex-col gap-1">
        <label className="text-[11px] font-medium text-fg-muted">
          摘要 model
        </label>
        <p className="text-[10px] text-fg-subtle">
          壓縮本身打的 LLM call。預設 Haiku 比用對話 model 便宜 ~5x;
          可選擇任一已設 API key 的 provider × model。
        </p>
        <select
          value={summaryValue}
          onChange={(e) => {
            const v = e.target.value
            if (!v) {
              setSummary(null, null)
              return
            }
            const [p, ...rest] = v.split('/')
            setSummary(p, rest.join('/'))
          }}
          className="w-64 rounded-md border border-bg-hover bg-bg-input px-2 py-1 text-xs focus:border-accent focus:outline-none"
        >
          <option value="">跟對話用同一個 model</option>
          {providers
            .filter((p) => p.api_key_configured)
            .flatMap((p) =>
              p.models.map((m) => (
                <option key={`${p.id}/${m.id}`} value={`${p.id}/${m.id}`}>
                  {p.label} · {m.label}
                </option>
              )),
            )}
        </select>
      </div>
    </div>
  )
}

/** 對話後續建議句 — 每 turn 完背景生 3 條使用者可能想接著問的話,輸入框上方
 * 顯 chip,點 / Tab 採用。每 turn 多一次小 LLM call(走「摘要 model」),所以
 * 預設關。 */
function FollowUpsPicker() {
  const enabled = useSettingsStore((s) => s.followUpsEnabled)
  const setEnabled = useSettingsStore((s) => s.setFollowUpsEnabled)
  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Sparkles size={14} />
        對話後續建議
      </h3>
      <p className="text-[11px] text-fg-subtle">
        每個 AI 回覆結束後,用「摘要 model」猜 3 條你可能想接著問的話,顯在輸入框上方,
        點或按 Tab 採用。預設關,因為每 turn 多一次 LLM call,有 token 成本。
      </p>
      <label className="mt-1 flex w-fit cursor-pointer items-center gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-1.5 text-sm hover:border-accent/40 hover:bg-bg-hover">
        <input
          type="checkbox"
          className="accent-accent"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <span>顯示後續建議句</span>
      </label>
    </div>
  )
}

/** STT (speech-to-text) provider + model 選擇 — catalog 來自 orion-model
 * 經 sidecar stt.status RPC。本來放 General,移過來跟 chat model 同 section,
 * 因為兩者都是 "選 model"。 */
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
