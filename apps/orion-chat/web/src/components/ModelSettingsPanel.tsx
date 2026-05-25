import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import { useTranslation } from '../i18n'
import { useModelCatalog } from '../hooks/useModelCatalog'
import {
  getPreferredModel,
  setPreferredModel,
  type ModelChoice,
} from '../lib/preferredModel'

/**
 * Model 設定 — 選「新對話預設 model」+ 看各 provider 的 API key 狀態 + STT 可用性。
 * 預設 model 存 localStorage(preferredModel),新對話 draft 會帶它;不改既有 session。
 */
export function ModelSettingsPanel() {
  const { t } = useTranslation()
  const { catalog, loading, error } = useModelCatalog()
  const [selected, setSelected] = useState<ModelChoice | null>(
    getPreferredModel(),
  )
  const [stt, setStt] = useState<boolean | null>(null)

  useEffect(() => {
    let alive = true
    void apiFetch<{ stt_available: boolean }>('/voice/status')
      .then((r) => {
        if (alive) setStt(r.stt_available)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  // 沒手動選過 → 預設視為 catalog.default
  const active = selected ?? catalog?.default ?? null

  function pick(provider: string, model: string) {
    const choice = { provider, model }
    setPreferredModel(choice)
    setSelected(choice)
  }

  return (
    <div className="p-5 space-y-5">
      <div>
        <div className="font-medium text-claude-text text-[13px]">
          {t('settings.model.defaultHeading')}
        </div>
        <div className="text-[12px] text-claude-textDim mt-0.5">
          {t('settings.model.defaultHint')}
        </div>
      </div>

      {loading && (
        <div className="text-[13px] text-claude-textDim">
          {t('settings.model.loading')}
        </div>
      )}
      {error && (
        <div className="text-[13px] text-red-600">
          {t('settings.model.failed')}
        </div>
      )}

      {catalog?.providers.map((p) => (
        <div key={p.id} className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-wider text-claude-textFaint">
              {p.label}
            </span>
            <span
              className={`text-[11px] ${
                p.available ? 'text-emerald-600' : 'text-amber-600'
              }`}
            >
              {p.available
                ? t('settings.model.keySet')
                : t('settings.model.keyMissing')}
            </span>
          </div>
          <div className="space-y-0.5">
            {p.models.map((m) => {
              const isActive =
                active?.provider === p.id && active?.model === m.id
              return (
                <button
                  key={m.id}
                  type="button"
                  disabled={!p.available}
                  onClick={() => pick(p.id, m.id)}
                  className={`w-full text-left px-3 py-2 rounded-md flex items-center gap-2 transition-colors ${
                    !p.available
                      ? 'text-claude-textFaint cursor-not-allowed'
                      : isActive
                        ? 'bg-claude-orangeSoft/40 text-claude-text'
                        : 'text-claude-text hover:bg-claude-borderSoft/60'
                  }`}
                >
                  <span className="flex-1 text-[13px]">{m.label}</span>
                  <span className="font-mono text-[11px] text-claude-textFaint">
                    {m.id}
                  </span>
                  {isActive && (
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                      <path
                        d="M3 8l3.5 3.5L13 5"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="text-claude-orange"
                      />
                    </svg>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      ))}

      <div className="border-t border-claude-border/60 pt-4">
        <div className="font-medium text-claude-text text-[13px]">
          {t('settings.model.voiceHeading')}
        </div>
        <div className="text-[12px] text-claude-textDim mt-0.5">
          {stt === null
            ? t('settings.model.loading')
            : stt
              ? t('settings.model.sttOn')
              : t('settings.model.sttOff')}
        </div>
      </div>
    </div>
  )
}
