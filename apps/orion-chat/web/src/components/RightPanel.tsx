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
          <div>${cost ? cost.total_cost_usd.toFixed(4) : '0.0000'}</div>
          {ctx && (
            <div className="text-[12px]">
              {t('panel.contextTokens', { n: ctx.approx_total_tokens })} ·{' '}
              {t('panel.messages', { n: ctx.n_messages })}
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
