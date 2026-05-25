import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import { useTranslation } from '../i18n'
import { deriveDetail } from '../lib/detailPanel'
import type { CostSummary, ServerEvent } from '../types/events'

interface ContextBreakdown {
  n_messages: number
  approx_total_tokens: number
  by_role_chars: Record<string, number>
}

/** 已知 origin → i18n label;未知的直接顯原字串。 */
function originLabel(
  t: (k: string) => string,
  origin: string,
): string {
  const keys: Record<string, string> = {
    chat: 'panel.origin.chat',
    title: 'panel.origin.title',
    follow_ups: 'panel.origin.followUps',
  }
  return keys[origin] ? t(keys[origin]) : origin
}

interface Props {
  sessionId: string | null
  events: ServerEvent[]
  refreshKey: number | string
}

const STATUS_COLOR: Record<string, string> = {
  completed: 'text-emerald-600',
  in_progress: 'text-amber-600',
  pending: 'text-claude-textFaint',
}

export function RightPanel({ sessionId, events, refreshKey }: Props) {
  const { t } = useTranslation()
  const { todos, skills } = deriveDetail(events)
  const [cost, setCost] = useState<CostSummary | null>(null)
  const [ctx, setCtx] = useState<ContextBreakdown | null>(null)

  useEffect(() => {
    if (!sessionId) {
      setCost(null)
      setCtx(null)
      return
    }
    let alive = true
    void (async () => {
      try {
        const [c, x] = await Promise.all([
          apiFetch<CostSummary>(`/sessions/${sessionId}/cost`),
          apiFetch<ContextBreakdown>(
            `/sessions/${sessionId}/context-breakdown`,
          ),
        ])
        if (alive) {
          setCost(c)
          setCtx(x)
        }
      } catch {
        /* 面板資訊性,失敗忽略 */
      }
    })()
    return () => {
      alive = false
    }
  }, [sessionId, refreshKey])

  return (
    <aside className="w-[280px] shrink-0 border-l border-claude-border/60 bg-claude-panel/40 overflow-y-auto p-4 space-y-5 text-[13px]">
      <Section title={t('panel.progress')}>
        {todos.length === 0 ? (
          <Empty t={t} />
        ) : (
          <ul className="space-y-1">
            {todos.map((td, i) => (
              <li key={i} className="flex gap-2">
                <span className={STATUS_COLOR[td.status] ?? ''}>•</span>
                <span
                  className={
                    td.status === 'completed'
                      ? 'line-through text-claude-textFaint'
                      : ''
                  }
                >
                  {td.content}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t('panel.skills')}>
        {skills.length === 0 ? (
          <Empty t={t} />
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {skills.map((s) => (
              <span
                key={s}
                className="px-1.5 py-0.5 rounded bg-claude-borderSoft text-[12px] font-mono"
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section title={t('panel.cost')}>
        <div className="space-y-1 text-claude-textDim">
          <div className="text-[15px] text-claude-text">
            ${cost ? cost.total_cost_usd.toFixed(4) : '0.0000'}
          </div>
          {(() => {
            const inTok = cost?.input_tokens ?? 0
            const outTok = cost?.output_tokens ?? 0
            const cacheTok =
              (cost?.cache_read_tokens ?? 0) +
              (cost?.cache_creation_tokens ?? 0)
            const total = inTok + outTok + cacheTok
            if (total === 0) {
              return (
                <div className="text-[12px] text-claude-textFaint">
                  {t('panel.noUsage')}
                </div>
              )
            }
            return (
              <>
                <div className="text-[12px]">
                  {t('panel.tokensTotal', { n: total.toLocaleString() })}
                </div>
                <div className="text-[12px] text-claude-textFaint">
                  {t('panel.tokensIO', {
                    in: inTok.toLocaleString(),
                    out: outTok.toLocaleString(),
                  })}
                  {cacheTok > 0 &&
                    ` · ${t('panel.tokensCache', { n: cacheTok.toLocaleString() })}`}
                </div>
              </>
            )
          })()}
          {ctx && (
            <div className="text-[12px] text-claude-textFaint">
              {t('panel.messages', { n: ctx.n_messages })}
            </div>
          )}
          {cost?.by_origin && Object.keys(cost.by_origin).length > 1 && (
            <div className="mt-1.5 pt-1.5 border-t border-claude-border/40 space-y-0.5">
              {Object.entries(cost.by_origin)
                .sort((a, b) => b[1].cost_usd - a[1].cost_usd)
                .map(([origin, u]) => (
                  <div
                    key={origin}
                    className="flex items-center justify-between text-[12px] text-claude-textFaint"
                  >
                    <span>{originLabel(t, origin)}</span>
                    <span className="font-mono">${u.cost_usd.toFixed(4)}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
      </Section>
    </aside>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] uppercase tracking-wider text-claude-textFaint">
        {title}
      </div>
      {children}
    </div>
  )
}

function Empty({ t }: { t: (k: string) => string }) {
  return (
    <div className="text-[12px] text-claude-textFaint italic">
      {t('panel.empty')}
    </div>
  )
}
