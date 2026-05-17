import { useState } from 'react'
import { Check, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { planApprove, planReject } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'
import { useSendPrompt } from '../hooks/useAgent'

export function PlanApprovalModal() {
  const { t } = useTranslation()
  const sid = useAgentStore((s) => s.sessionId)
  const pending = useAgentStore((s) =>
    sid ? s.pendingPlanApprovalBySession[sid] : null,
  )
  const clearPending = useAgentStore((s) => s.clearPendingPlanApproval)
  const setPlanModeStatus = useAgentStore((s) => s.setPlanModeStatus)
  const sendPrompt = useSendPrompt()
  const [feedback, setFeedback] = useState('')
  const [busy, setBusy] = useState(false)

  if (!sid || !pending) return null

  async function handleApprove() {
    if (busy || !sid) return
    setBusy(true)
    try {
      const result = await planApprove(sid)
      clearPending(sid)
      setPlanModeStatus(sid, 'idle')
      setFeedback('')
      // 自動送 follow_up 作為下一輪 user message
      await sendPrompt(result.follow_up)
    } finally {
      setBusy(false)
    }
  }

  async function handleReject() {
    if (busy || !sid) return
    setBusy(true)
    try {
      const result = await planReject(sid, feedback.trim() || undefined)
      clearPending(sid)
      setPlanModeStatus(sid, 'idle')
      setFeedback('')
      await sendPrompt(result.follow_up)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="text-sm font-semibold">{t('plan.modal.title')}</h2>
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-500">
            {t('plan.modal.awaitingTag')}
          </span>
        </header>
        <div className="overflow-y-auto px-5 py-4">
          <p className="mb-3 text-xs text-fg-muted">
            {t('plan.modal.description')}
          </p>
          <div className="prose prose-sm prose-invert max-w-none rounded-lg border border-bg-hover bg-bg-input p-4">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {pending.planMarkdown || '*(empty plan)*'}
            </ReactMarkdown>
          </div>
          <label className="mt-4 block text-xs text-fg-muted">
            {t('plan.modal.feedbackLabel')}
          </label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder={t('plan.modal.feedbackPlaceholder')}
            rows={2}
            className="mt-1 w-full rounded-md border border-bg-hover bg-bg-input px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-bg-hover px-5 py-3">
          <button
            type="button"
            onClick={handleReject}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md border border-bg-hover px-3 py-1.5 text-sm hover:bg-bg-hover disabled:opacity-50"
          >
            <X size={14} />
            {t('plan.modal.reject')}
          </button>
          <button
            type="button"
            onClick={handleApprove}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm text-white hover:bg-accent/90 disabled:opacity-50"
          >
            <Check size={14} />
            {t('plan.modal.approve')}
          </button>
        </footer>
      </div>
    </div>
  )
}
