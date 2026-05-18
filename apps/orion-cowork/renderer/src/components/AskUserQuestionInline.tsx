/**
 * Inline UI for AskUserQuestion tool — render 在訊息流中,給 user 點選項或填答。
 *
 * 接 sidecar 推來的 ask_user_question frame(via agent store.pendingQuestion),
 * user 填答送出後呼 conversation.ask_user_reply RPC,backend resolve future,
 * tool 回傳 TextEvent("User answers: ..."),LLM 繼續下一輪。
 *
 * 設計:每題獨立區塊,multi_select 用 checkbox group / single 用 radio 樣式
 * 按鈕。沒 options 的開放題顯 textarea。底部一鍵「送出」打包所有答案 reply。
 */
import { useEffect, useState } from 'react'
import { Check, ChevronLeft, ChevronRight, Sparkles } from 'lucide-react'

import { sendAskUserReply, type AskQuestion } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'

/** Sentinel label for the auto-injected「其他」option — submit 時換成 otherTexts。 */
const OTHER = '__other__'

export function AskUserQuestionInline({ assistantId }: { assistantId: string }) {
  const { t } = useTranslation()
  const sid = useAgentStore((s) => s.sessionId)
  const pending: import('../store/agent').PendingQuestion | null = useAgentStore((s) =>
    s.sessionId ? s.pendingQuestionBySession[s.sessionId] ?? null : null,
  )
  const setPending = useAgentStore((s) => s.setPendingQuestion)
  const [drafts, setDrafts] = useState<Record<string, string[]>>({})
  // 每題的「其他」自填文字。即使 user 沒勾 Other 也可先打字,勾了才生效。
  const [otherTexts, setOtherTexts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  // 多題時的當前頁籤;切換 pendingQuestion 時 reset。
  const [activeIdx, setActiveIdx] = useState(0)
  useEffect(() => {
    setActiveIdx(0)
    setDrafts({})
    setOtherTexts({})
  }, [pending?.requestId])

  if (!pending || pending.assistantId !== assistantId) return null

  function setSingle(qText: string, label: string) {
    setDrafts((d) => ({ ...d, [qText]: [label] }))
  }
  function toggleMulti(qText: string, label: string) {
    setDrafts((d) => {
      const cur = d[qText] ?? []
      const has = cur.includes(label)
      return {
        ...d,
        [qText]: has ? cur.filter((x) => x !== label) : [...cur, label],
      }
    })
  }
  function setFreeText(qText: string, text: string) {
    setDrafts((d) => ({ ...d, [qText]: [text] }))
  }
  function setOther(qText: string, text: string) {
    setOtherTexts((d) => ({ ...d, [qText]: text }))
  }

  // 一題算「答完」的條件:有任何 pick;且若 pick 含 Other,otherText 非空
  function questionReady(qText: string): boolean {
    const picks = drafts[qText] ?? []
    if (picks.length === 0) return false
    if (picks.includes(OTHER) && !(otherTexts[qText] ?? '').trim()) return false
    return true
  }

  function readyToSubmit(): boolean {
    return pending!.questions.every((q) => questionReady(q.question))
  }

  async function submit() {
    if (!pending || busy || !readyToSubmit()) return
    setBusy(true)
    try {
      const answers: Record<string, string> = {}
      for (const q of pending.questions) {
        const picks = drafts[q.question] ?? []
        // 把 OTHER sentinel 換成實際自填文字
        const resolved = picks.map((p) =>
          p === OTHER ? (otherTexts[q.question] ?? '').trim() : p,
        )
        answers[q.question] = resolved.filter(Boolean).join(', ')
      }
      await sendAskUserReply(pending.requestId, answers)
    } finally {
      setBusy(false)
      if (sid) setPending(sid, null)
    }
  }

  const total = pending.questions.length
  const isMulti = total > 1
  const current = pending.questions[activeIdx]
  const onLast = activeIdx === total - 1
  const onFirst = activeIdx === 0

  return (
    <div className="mt-2 rounded-2xl border border-accent/30 bg-accent/5 p-4">
      <div className="mb-3 flex items-center gap-2 text-xs font-medium text-accent">
        <Sparkles size={12} />
        <span>{t('askUser.title')}</span>
        {isMulti && (
          <span className="text-fg-muted">
            ({activeIdx + 1} / {total})
          </span>
        )}
      </div>
      {/* 頁籤 — 多題才顯,點任一題跳過去 */}
      {isMulti && (
        <div className="scrollbar-thin mb-3 flex gap-1 overflow-x-auto">
          {pending.questions.map((q, i) => {
            const done = questionReady(q.question)
            const active = i === activeIdx
            return (
              <button
                key={i}
                type="button"
                onClick={() => setActiveIdx(i)}
                className={`flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors ${
                  active
                    ? 'bg-accent text-white'
                    : done
                      ? 'bg-success/15 text-success hover:bg-success/25'
                      : 'bg-bg-hover text-fg-muted hover:bg-bg-hover/80 hover:text-fg-base'
                }`}
              >
                {done && !active ? (
                  <Check size={11} />
                ) : (
                  <span className="font-mono text-[10px] opacity-70">{i + 1}</span>
                )}
                <span className="max-w-[120px] truncate">
                  {q.header || `Q${i + 1}`}
                </span>
              </button>
            )
          })}
        </div>
      )}
      <QuestionBlock
        q={current}
        picks={drafts[current.question] ?? []}
        otherText={otherTexts[current.question] ?? ''}
        onPick={(label) =>
          current.multi_select
            ? toggleMulti(current.question, label)
            : setSingle(current.question, label)
        }
        onFreeText={(text) => setFreeText(current.question, text)}
        onOtherText={(text) => setOther(current.question, text)}
      />
      <div className="mt-4 flex items-center justify-between gap-2">
        {isMulti ? (
          <button
            type="button"
            onClick={() => setActiveIdx((i) => Math.max(0, i - 1))}
            disabled={onFirst}
            className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:cursor-not-allowed disabled:opacity-30"
          >
            <ChevronLeft size={12} />
            <span>{t('askUser.prev')}</span>
          </button>
        ) : (
          <span />
        )}
        {isMulti && !onLast ? (
          <button
            type="button"
            onClick={() => setActiveIdx((i) => Math.min(total - 1, i + 1))}
            disabled={!questionReady(current.question)}
            className="flex items-center gap-1 rounded-md bg-bg-hover px-3 py-1.5 text-sm font-medium text-fg-base hover:bg-bg-hover/80 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span>{t('askUser.next')}</span>
            <ChevronRight size={12} />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={busy || !readyToSubmit()}
            className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t('askUser.submit')}
          </button>
        )}
      </div>
    </div>
  )
}

function QuestionBlock({
  q,
  picks,
  otherText,
  onPick,
  onFreeText,
  onOtherText,
}: {
  q: AskQuestion
  picks: string[]
  otherText: string
  onPick: (label: string) => void
  onFreeText: (text: string) => void
  onOtherText: (text: string) => void
}) {
  const { t } = useTranslation()
  const hasOptions = q.options.length > 0
  const otherPicked = picks.includes(OTHER)

  return (
    <div className="flex flex-col gap-2">
      {q.header && (
        <span className="self-start rounded-full bg-bg-hover px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-fg-muted">
          {q.header}
        </span>
      )}
      <p className="text-sm font-medium text-fg-base">{q.question}</p>
      {hasOptions ? (
        <div className="flex flex-col gap-1.5">
          {q.options.map((opt, i) => {
            const active = picks.includes(opt.label)
            return (
              <OptionButton
                key={i}
                label={opt.label}
                description={opt.description}
                active={active}
                multi={q.multi_select}
                onClick={() => onPick(opt.label)}
              />
            )
          })}
          {/* 自動補一個 Other,讓 user 自填 — 跟 Claude 的 AskUserQuestion 一致 */}
          <OptionButton
            label={t('askUser.other')}
            active={otherPicked}
            multi={q.multi_select}
            onClick={() => onPick(OTHER)}
          />
          {otherPicked && (
            <textarea
              value={otherText}
              onChange={(e) => onOtherText(e.target.value)}
              placeholder={t('askUser.openPlaceholder')}
              rows={2}
              autoFocus
              className="scrollbar-thin ml-6 resize-none rounded-md border border-bg-hover bg-bg-input px-3 py-2 text-sm focus:border-accent focus:outline-none"
            />
          )}
        </div>
      ) : (
        <textarea
          value={picks[0] ?? ''}
          onChange={(e) => onFreeText(e.target.value)}
          placeholder={t('askUser.openPlaceholder')}
          rows={2}
          className="scrollbar-thin resize-none rounded-md border border-bg-hover bg-bg-input px-3 py-2 text-sm focus:border-accent focus:outline-none"
        />
      )}
    </div>
  )
}

function OptionButton({
  label,
  description,
  active,
  multi,
  onClick,
}: {
  label: string
  description?: string
  active: boolean
  multi: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
        active
          ? 'border-accent bg-accent/10 text-fg-base'
          : 'border-bg-hover bg-bg-panel text-fg-base hover:border-accent/40 hover:bg-bg-hover'
      }`}
    >
      <span
        className={`mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center ${
          multi ? 'rounded-sm' : 'rounded-full'
        } border ${active ? 'border-accent bg-accent' : 'border-fg-subtle'}`}
      >
        {active && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
      </span>
      <span className="flex flex-col gap-0.5">
        <span>{label}</span>
        {description && (
          <span className="text-xs text-fg-muted">{description}</span>
        )}
      </span>
    </button>
  )
}
