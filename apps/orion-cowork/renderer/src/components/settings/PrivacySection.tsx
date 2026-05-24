import { Info, ShieldCheck } from 'lucide-react'

import { useTranslation } from '../../i18n'
import { useSettingsStore } from '../../store/settings'

/**
 * 隱私 / 資料 — 控 sidecar 保留多少「真實送 LLM 的 wire payload」snapshot。
 *
 * - N = 0:完全不存,user 點「為什麼?」拿到的對話內容走 fallback 顯
 *   messagesBySession(UI 版本,跟 wire 略有差異)
 * - N = 1(default):看最近一次,儲存增加極少
 * - N up to 20:paranoid 上限(設這麼大基本只有專業 audit / debug 用)
 *
 * Wire snapshot 含 sidecar conv.state_messages(含 tool result content / role
 * 對齊 wire),但 SDK 自動 inject 的 memory / git_status / per_turn_text 不在
 * (那部分是 SDK conv.send 內 local 變數,sidecar 看不到)。
 */
export function PrivacySection() {
  const { t } = useTranslation()
  const n = useSettingsStore((s) => s.auditWirePayloadHistory)
  const setN = useSettingsStore((s) => s.setAuditWirePayloadHistory)

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="flex items-center gap-2 text-xl font-semibold text-fg-base">
          <ShieldCheck size={18} className="text-accent" />
          {t('settings.section.privacy')}
        </h2>
        <p className="text-sm text-fg-muted">{t('privacy.intro')}</p>
      </header>

      {/* A1 read-only 說明 — 讓 user 知道整體 audit 邏輯 */}
      <section className="space-y-2 rounded-md border border-bg-hover bg-bg-panel/40 px-4 py-3">
        <h3 className="flex items-center gap-1.5 text-sm font-medium text-fg-muted">
          <Info size={13} />
          {t('privacy.turnAudit.title')}
        </h3>
        <p className="text-[11px] text-fg-subtle whitespace-pre-line">
          {t('privacy.turnAudit.desc')}
        </p>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-medium text-fg-muted">{t('privacy.wireAudit.title')}</h3>
        <p className="text-[11px] text-fg-subtle">{t('privacy.wireAudit.desc')}</p>
        <div className="flex items-center gap-3">
          <input
            type="number"
            min={0}
            max={20}
            step={1}
            value={n}
            onChange={(e) => setN(Number(e.target.value || 0))}
            className="w-20 rounded-md border border-bg-hover bg-bg-input px-2 py-1 text-sm focus:border-accent focus:outline-none"
          />
          <span className="text-[11px] text-fg-subtle">{t('privacy.wireAudit.unit')}</span>
        </div>
        <div className="mt-2 rounded-md border border-bg-hover bg-bg-panel/40 px-3 py-2 text-[11px] text-fg-muted">
          {n === 0 && t('privacy.wireAudit.modeOff')}
          {n === 1 && t('privacy.wireAudit.modeDefault')}
          {n > 1 && n <= 5 && t('privacy.wireAudit.modeFew', { n: String(n) })}
          {n > 5 && t('privacy.wireAudit.modeMany', { n: String(n) })}
        </div>
      </section>
    </div>
  )
}
