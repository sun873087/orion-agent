import { useState } from 'react'
import type { AskUserQuestionAskEvent } from '../types/events'

interface Props {
  event: AskUserQuestionAskEvent
  onAnswer?: (answers: Record<string, string>) => void
  /** 已回答的歷史卡片:傳這個就走 readonly 模式,顯示「✓ 已回答」。 */
  answers?: Record<string, string>
}

/**
 * 模型透過 AskUserQuestion tool 反問使用者時的對話框。
 *
 * 三種題型:
 * - 有 options + multi_select=false → buttons,點一下就送
 * - 有 options + multi_select=true  → checkbox + Submit(逗號串多選 label)
 * - 無 options                       → text input + Submit
 *
 * 一次可問多題(backend min=1, max=4),全部答完才送。
 */
export function AskUserQuestionDialog({ event, onAnswer, answers }: Props) {
  const readonly = answers !== undefined
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  function setDraft(question: string, value: string) {
    setDrafts((prev) => ({ ...prev, [question]: value }))
  }

  function toggleMulti(question: string, label: string) {
    setDrafts((prev) => {
      const cur = prev[question]
        ? prev[question].split(', ').filter(Boolean)
        : []
      const next = cur.includes(label)
        ? cur.filter((l) => l !== label)
        : [...cur, label]
      return { ...prev, [question]: next.join(', ') }
    })
  }

  function submitAll() {
    if (!onAnswer) return
    const out: Record<string, string> = {}
    for (const q of event.questions) {
      out[q.question] = drafts[q.question] ?? ''
    }
    onAnswer(out)
  }

  function answerSingle(question: string, label: string) {
    if (!onAnswer) return
    // 單題、單選 → 直接送(若還有其他未答題,先 setDraft 再讓 user 按 submit)
    if (event.questions.length === 1) {
      onAnswer({ [question]: label })
      return
    }
    setDraft(question, label)
  }

  const allAnswered = event.questions.every(
    (q) => (drafts[q.question] ?? '').length > 0,
  )
  const needsSubmit =
    event.questions.length > 1 ||
    event.questions.some((q) => q.options.length === 0 || q.multi_select)

  return (
    <div
      className={
        'rounded-xl p-4 animate-fade-in border ' +
        (readonly
          ? 'border-claude-border bg-white/40 dark:bg-claude-panel/40'
          : 'border-claude-orange/40 bg-claude-orangeSoft/40')
      }
    >
      <div className="flex items-start gap-2.5 mb-3">
        <svg
          width="18"
          height="18"
          viewBox="0 0 18 18"
          fill="none"
          className={
            'shrink-0 mt-0.5 ' +
            (readonly ? 'text-claude-textDim' : 'text-claude-orange')
          }
        >
          {readonly ? (
            <path
              d="M4 9.5l3.5 3.5L14 6"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          ) : (
            <>
              <circle
                cx="9"
                cy="9"
                r="7"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path
                d="M7 7a2 2 0 114 0c0 1-1 1.5-2 2.2M9 12.5h.01"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </>
          )}
        </svg>
        <div>
          <div className="font-medium text-claude-text text-[14px]">
            {readonly ? '已回答' : 'Orion 想問你'}
          </div>
          {!readonly && (
            <div className="text-[12px] text-claude-textDim mt-0.5">
              回答後對話會繼續。
            </div>
          )}
        </div>
      </div>

      <div className="space-y-4">
        {event.questions.map((q, qi) => {
          const value = readonly
            ? (answers![q.question] ?? '')
            : (drafts[q.question] ?? '')
          const chosen = value.split(', ').filter(Boolean)
          return (
            <div key={qi} className="space-y-2">
              <div className="flex items-baseline gap-2">
                {q.header && (
                  <span
                    className={
                      'text-[10px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded border ' +
                      (readonly
                        ? 'text-claude-textDim bg-white/40 dark:bg-claude-panel/40 border-claude-border'
                        : 'text-claude-orange bg-white/70 dark:bg-claude-panel/70 border-claude-orange/30')
                    }
                  >
                    {q.header}
                  </span>
                )}
                <span className="text-[13px] text-claude-text">
                  {q.question}
                </span>
              </div>

              {q.options.length === 0 ? (
                readonly ? (
                  <div className="text-[13px] text-claude-text bg-white/60 dark:bg-claude-panel/60 border border-claude-border rounded-md px-3 py-1.5">
                    {value || (
                      <span className="text-claude-textFaint">(空)</span>
                    )}
                  </div>
                ) : (
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => setDraft(q.question, e.target.value)}
                    placeholder="輸入回答..."
                    className="w-full px-3 py-1.5 bg-white dark:bg-claude-panel border border-claude-border rounded-md text-[13px] focus:outline-none focus:border-claude-orange"
                  />
                )
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {q.options.map((opt, oi) => {
                    const selected = q.multi_select
                      ? chosen.includes(opt.label)
                      : value === opt.label
                    const baseClasses =
                      'px-3 py-1.5 rounded-md text-[13px] border transition-colors '
                    const styleClasses = selected
                      ? 'bg-claude-orange text-white border-claude-orange'
                      : 'bg-white dark:bg-claude-panel border-claude-border text-claude-text'
                    const hoverClasses = readonly
                      ? ' opacity-70 cursor-default'
                      : ' hover:bg-claude-borderSoft'
                    return (
                      <button
                        key={oi}
                        type="button"
                        disabled={readonly}
                        title={opt.description}
                        onClick={() =>
                          q.multi_select
                            ? toggleMulti(q.question, opt.label)
                            : answerSingle(q.question, opt.label)
                        }
                        className={baseClasses + styleClasses + hoverClasses}
                      >
                        {selected && readonly ? '✓ ' : ''}
                        {opt.label}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {!readonly && needsSubmit && (
        <div className="flex items-center justify-end gap-2 mt-4">
          <button
            type="button"
            onClick={() => onAnswer?.({})}
            className="px-3 py-1.5 text-[13px] text-claude-textDim hover:text-claude-text"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!allAnswered}
            onClick={submitAll}
            className="px-3.5 py-1.5 bg-claude-orange text-white rounded-md hover:bg-claude-orangeHover text-[13px] font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            送出
          </button>
        </div>
      )}

      {!readonly && event.timeout_seconds && (
        <div className="text-[11px] text-claude-textFaint mt-2">
          Timeout: {event.timeout_seconds}s
        </div>
      )}
    </div>
  )
}
