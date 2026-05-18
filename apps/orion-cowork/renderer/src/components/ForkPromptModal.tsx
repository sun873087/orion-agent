/**
 * 分叉對話的輸入 modal — Phase 31-R。
 *
 * 訂閱 useAgentStore.forkRequest;非 null 時 render,渲染在 App.tsx top-level
 * (跟 NewProjectModal / PlanApprovalModal 同位置),完全避開 chat / MessageBubble
 * 父層 CSS / event 影響。
 *
 * 行為依 fork 點 role 區分:
 *   - 從 user 訊息分叉:輸入框是「新訊息」— 空 = 用原訊息重 ask AI,有值
 *     = 換問法。title 從新訊息前 60 字自動取
 *   - 從 assistant 訊息分叉:輸入框是「分支標題」— user 之後在輸入框打下個 prompt
 *
 * Enter 送出、Esc 取消、點背景關閉。
 */
import { useEffect, useState } from 'react'
import { GitBranch } from 'lucide-react'

import { useFork } from '../hooks/useAgent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'

export function ForkPromptModal() {
  const { t } = useTranslation()
  const req = useAgentStore((s) => s.forkRequest)
  const close = useAgentStore((s) => s.closeForkRequest)
  const fork = useFork()
  const [draft, setDraft] = useState('')

  // 開新一輪 modal 時清舊 draft;切不同訊息 fork 也對齊
  useEffect(() => {
    setDraft('')
  }, [req?.sessionId, req?.messageIndex])

  if (!req) return null

  const isUserFork = req.forkPointRole === 'user'

  async function submit() {
    const text = draft.trim()
    setDraft('')
    close()
    if (!req) return
    if (isUserFork) {
      // 輸入是「新訊息」— 空 = 重發原訊息(只給 title 走 source title 自動),
      // 有值 = 用它當新 prompt + title 自動截前 60 字
      await fork(req.messageIndex, undefined, text || undefined)
    } else {
      // 輸入是「分支標題」— 沒 auto-continue
      await fork(req.messageIndex, text || undefined)
    }
  }

  function cancel() {
    setDraft('')
    close()
  }

  // 依 role 切換 label / placeholder / hint / confirm 文字
  const heading = isUserFork
    ? t('message.forkPromptHeadingUser')
    : t('message.forkPromptHeadingAssistant')
  const hint = isUserFork
    ? t('message.forkPromptHintUser', { original: req.originalText.slice(0, 30) })
    : t('message.forkPromptHintAssistant')
  const placeholder = isUserFork
    ? t('message.forkInputPlaceholderUser')
    : t('message.forkInputPlaceholderAssistant')

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
          {heading}
        </h2>
        <p className="text-xs text-fg-muted">{hint}</p>
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void submit()
            } else if (e.key === 'Escape') {
              cancel()
            }
          }}
          placeholder={placeholder}
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
