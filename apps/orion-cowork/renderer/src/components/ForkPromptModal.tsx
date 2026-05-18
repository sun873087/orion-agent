/**
 * 分叉對話的標題輸入 modal — Phase 31-R。
 *
 * 訂閱 useAgentStore.forkRequest;非 null 時 render,渲染在 App.tsx top-level
 * (跟 NewProjectModal / PlanApprovalModal 同位置),完全避開 chat / MessageBubble
 * 父層 CSS / event 影響。Enter 送出、Esc 取消、點背景關閉;標題留空 = source
 * title 自動帶「(fork)」。送出後切到新 session。
 */
import { useState } from 'react'
import { GitBranch } from 'lucide-react'

import { useFork } from '../hooks/useAgent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'

export function ForkPromptModal() {
  const { t } = useTranslation()
  const req = useAgentStore((s) => s.forkRequest)
  const close = useAgentStore((s) => s.closeForkRequest)
  const fork = useFork()
  const [title, setTitle] = useState('')

  if (!req) return null

  async function submit() {
    const text = title.trim()
    setTitle('')
    close()
    if (!req) return
    await fork(req.messageIndex, text || undefined)
  }

  function cancel() {
    setTitle('')
    close()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={cancel}
    >
      <div
        className="flex w-full max-w-md flex-col gap-3 rounded-2xl border border-bg-hover bg-bg-base p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <GitBranch size={14} />
          {t('message.fork')}
        </h2>
        <p className="text-xs text-fg-muted">{t('message.forkPromptTitle')}</p>
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void submit()
            } else if (e.key === 'Escape') {
              cancel()
            }
          }}
          placeholder={t('message.forkTitlePlaceholder')}
          className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            className="rounded-md px-3 py-1.5 text-xs text-fg-muted hover:bg-bg-hover"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90"
          >
            {t('message.forkConfirm')}
          </button>
        </div>
      </div>
    </div>
  )
}
