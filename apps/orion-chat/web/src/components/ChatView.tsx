import { useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch } from '../api/client'
import { useTranslation } from '../i18n'
import { useWebSocket } from '../hooks/useWebSocket'
import { useSessionStore } from '../store/sessionStore'
import type {
  ModelCatalog,
  SessionSummary,
  UploadSummary,
} from '../types/events'
import type { ModelChoice } from '../lib/preferredModel'
import { EMPTY, newId, reduce, type FlowState } from '../lib/chatFlow'
import { CostBadge } from './CostBadge'
import { MessageList } from './MessageList'
import { InputBox } from './InputBox'
import { ModelBadge } from './ModelBadge'
import { ModelPicker } from './ModelPicker'
import { PlanApprovalModal } from './PlanApprovalModal'
import { RightPanel } from './RightPanel'
import { WorkspaceFiles } from './WorkspaceFiles'

interface Props {
  sessionId: string | null
  token: string | null
  currentSession: SessionSummary | null
  catalog: ModelCatalog | null
  /** Draft mode: 使用者按 New chat 但還沒送訊息;sessionId 會是 null。 */
  draft: ModelChoice | null
  /** Draft mode 送第一則訊息時呼叫,實際建立 session 並回傳 sid。 */
  onCommitDraft: () => Promise<string | null>
  onOpenSettings: () => void
  onModelChange: (choice: ModelChoice) => void
}

export function ChatView({
  sessionId,
  token,
  currentSession,
  catalog,
  draft,
  onCommitDraft,
  onOpenSettings,
  onModelChange,
}: Props) {
  const { t } = useTranslation()
  const compact = useSessionStore((s) => s.compact)
  const ws = useWebSocket(sessionId, token)
  const [showPanel, setShowPanel] = useState(false)
  const [permMode, setPermMode] = useState<'ask' | 'act'>('ask')

  useEffect(() => {
    if (!sessionId) return
    let alive = true
    void apiFetch<{ mode: 'ask' | 'act' }>(
      `/sessions/${sessionId}/permission-mode`,
    )
      .then((r) => {
        if (alive) setPermMode(r.mode)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [sessionId])

  const [planStatus, setPlanStatus] = useState<
    'inactive' | 'active' | 'awaiting_approval'
  >('inactive')
  const [planContent, setPlanContent] = useState('')

  useEffect(() => {
    if (!sessionId) return
    let alive = true
    void apiFetch<{ status: typeof planStatus; content: string }>(
      `/sessions/${sessionId}/plan/status`,
    )
      .then((r) => {
        if (alive) {
          setPlanStatus(r.status)
          setPlanContent(r.content)
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [sessionId])

  async function planAction(action: 'enter' | 'exit' | 'approve' | 'reject') {
    if (!sessionId) return
    const r = await apiFetch<{ status: typeof planStatus; content?: string }>(
      `/sessions/${sessionId}/plan/${action}`,
      { method: 'POST' },
    ).catch(() => null)
    if (r) {
      setPlanStatus(r.status)
      setPlanContent(r.content ?? '')
    }
  }

  async function togglePermMode() {
    if (!sessionId) return
    const next = permMode === 'ask' ? 'act' : 'ask'
    setPermMode(next)
    await apiFetch(`/sessions/${sessionId}/permission-mode`, {
      method: 'PUT',
      body: { mode: next },
    }).catch(() => setPermMode(permMode))
  }

  async function setBudget() {
    if (!sessionId) return
    const raw = prompt(t('chat.budgetPrompt'))
    if (raw === null) return
    const cap = raw.trim() === '' ? null : Number(raw)
    if (cap !== null && Number.isNaN(cap)) return
    await apiFetch(`/sessions/${sessionId}/budget`, {
      method: 'PUT',
      body: { budget_usd_cap: cap },
    }).catch(() => {})
  }

  const [flow, setFlow] = useState<FlowState>(EMPTY)
  const processedCountRef = useRef(0)
  // draft → real session 之間的 pending message。sessionId 變動時 flow 會被
  // 重置成 EMPTY,所以這個訊息只能存在 ref 裡才不會被洗掉。WS open 後 flush。
  const pendingDraftSendRef = useRef<string | null>(null)

  useEffect(() => {
    setFlow(EMPTY)
    processedCountRef.current = 0
  }, [sessionId])

  // draft 模式下 commit 完 sid,等 WS open 後把訊息送出
  useEffect(() => {
    if (sessionId && ws.status === 'open' && pendingDraftSendRef.current) {
      const text = pendingDraftSendRef.current
      pendingDraftSendRef.current = null
      setFlow((s) => ({
        ...s,
        entries: [...s.entries, { kind: 'user', id: newId(), text }],
        inFlight: true,
      }))
      ws.send({ type: 'user_message', content: text })
    }
  }, [sessionId, ws.status, ws])

  // server 在 reconnect 會 replay history → useWebSocket reset events 為 [],
  // 我們也得把處理過的 cursor 同步歸零,否則新 events 會被當成「已處理」跳過。
  useEffect(() => {
    if (ws.events.length < processedCountRef.current) {
      processedCountRef.current = 0
      setFlow(EMPTY)
    }
  }, [ws.events])

  useEffect(() => {
    const start = processedCountRef.current
    if (ws.events.length <= start) return
    setFlow((prev) => {
      let next = prev
      for (let i = start; i < ws.events.length; i++) {
        next = reduce(next, ws.events[i]!)
      }
      return next
    })
    processedCountRef.current = ws.events.length
  }, [ws.events])

  // reconnect banner: reconnecting 超過 1s 才顯示,避免短暫抖動 flicker
  const [showReconnectBanner, setShowReconnectBanner] = useState(false)
  useEffect(() => {
    if (ws.status !== 'reconnecting') {
      setShowReconnectBanner(false)
      return
    }
    const t = setTimeout(() => setShowReconnectBanner(true), 1_000)
    return () => clearTimeout(t)
  }, [ws.status])

  function send(text: string, attachments: UploadSummary[]) {
    let combined = text
    if (attachments.length > 0) {
      const refs = attachments
        .map((a) => `[Attached: ${a.filename} (upload_id=${a.upload_id})]`)
        .join('\n')
      combined = combined ? `${combined}\n\n${refs}` : refs
    }
    if (!combined) return
    if (!sessionId) {
      // draft 模式:先建 session,WS open 後才實際發訊息
      if (!draft) return
      pendingDraftSendRef.current = combined
      void onCommitDraft().then((sid) => {
        if (!sid) pendingDraftSendRef.current = null
      })
      return
    }
    setFlow((s) => ({
      ...s,
      entries: [...s.entries, { kind: 'user', id: newId(), text: combined }],
      inFlight: true,
    }))
    ws.send({ type: 'user_message', content: combined })
  }

  const turnCount = useMemo(
    () => flow.entries.filter((e) => e.kind === 'turn_complete').length,
    [flow.entries],
  )

  const isEmpty =
    flow.entries.length === 0 && !flow.liveAssistant && !flow.liveThinking

  return (
    <div className="flex-1 flex min-w-0">
      <main className="flex-1 flex flex-col min-w-0 bg-claude-cream">
        <header className="flex items-center justify-between px-5 py-3 text-[13px]">
          <div className="flex items-center gap-2.5 text-claude-textDim">
            <span
              className={`inline-block h-2 w-2 rounded-full transition-colors ${
                ws.status === 'open'
                  ? 'bg-emerald-500'
                  : ws.status === 'connecting' || ws.status === 'reconnecting'
                    ? 'bg-amber-400 animate-pulse'
                    : 'bg-claude-textFaint'
              }`}
              title={ws.status}
            />
            <span className="font-mono text-claude-textDim">
              {sessionId
                ? `${sessionId.slice(0, 8)}…`
                : draft
                  ? 'new chat'
                  : 'no session'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <ModelBadge
              provider={currentSession?.provider}
              model={currentSession?.model}
              catalog={catalog}
            />
            <WorkspaceFiles sessionId={sessionId} refreshKey={turnCount} />
            {sessionId && (
              <button
                onClick={() =>
                  void planAction(planStatus === 'inactive' ? 'enter' : 'exit')
                }
                className={`px-2 py-0.5 rounded-md text-[12px] font-medium transition-colors ${
                  planStatus !== 'inactive'
                    ? 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                    : 'bg-claude-panel text-claude-textDim hover:text-claude-text'
                }`}
                title={t('chat.plan')}
              >
                {planStatus !== 'inactive'
                  ? t('chat.planActive')
                  : t('chat.plan')}
              </button>
            )}
            {sessionId && (
              <button
                onClick={() => void togglePermMode()}
                className={`px-2 py-0.5 rounded-md text-[12px] font-medium transition-colors ${
                  permMode === 'act'
                    ? 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                    : 'bg-claude-panel text-claude-textDim hover:text-claude-text'
                }`}
                title={t('chat.permMode')}
              >
                {permMode === 'act' ? t('chat.permAct') : t('chat.permAsk')}
              </button>
            )}
            <CostBadge sessionId={sessionId} refreshKey={turnCount} />
            {sessionId && (
              <button
                onClick={() => void setBudget()}
                className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
                title={t('chat.budget')}
                aria-label={t('chat.budget')}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <circle
                    cx="8"
                    cy="8"
                    r="6.5"
                    stroke="currentColor"
                    strokeWidth="1.3"
                  />
                  <path
                    d="M8 4.5v7M6 6.2c0-.8.9-1.2 2-1.2s2 .5 2 1.3-1 1.1-2 1.4-2 .6-2 1.4.9 1.4 2 1.4 2-.5 2-1.2"
                    stroke="currentColor"
                    strokeWidth="1.1"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            )}
            {sessionId && (
              <button
                onClick={() => setShowPanel((v) => !v)}
                className={`p-1.5 rounded-md transition-colors ${
                  showPanel
                    ? 'bg-claude-panel text-claude-text'
                    : 'text-claude-textDim hover:bg-claude-panel hover:text-claude-text'
                }`}
                title={t('panel.toggle')}
                aria-label={t('panel.toggle')}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <rect
                    x="2"
                    y="3"
                    width="12"
                    height="10"
                    rx="1.5"
                    stroke="currentColor"
                    strokeWidth="1.4"
                  />
                  <path d="M10 3v10" stroke="currentColor" strokeWidth="1.4" />
                </svg>
              </button>
            )}
            <button
              onClick={onOpenSettings}
              className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
              title="Settings"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
        </header>

        {showReconnectBanner && (
          <div className="px-5 py-2 text-[12px] text-amber-800 bg-amber-50 border-y border-amber-200 dark:text-amber-200 dark:bg-amber-950/40 dark:border-amber-900/50 flex items-center gap-2">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
            Reconnecting to server…
          </div>
        )}

        {flow.notice === 'budget' && (
          <div className="px-5 py-2 text-[12px] text-red-800 bg-red-50 border-y border-red-200 dark:text-red-200 dark:bg-red-950/40 dark:border-red-900/50 flex items-center justify-between gap-2">
            <span>{t('chat.budgetBanner')}</span>
            <button
              onClick={() => void setBudget()}
              className="underline hover:no-underline shrink-0"
            >
              {t('chat.budget')}
            </button>
          </div>
        )}
        {flow.notice === 'autocompact' && (
          <div className="px-5 py-2 text-[12px] text-amber-800 bg-amber-50 border-y border-amber-200 dark:text-amber-200 dark:bg-amber-950/40 dark:border-amber-900/50 flex items-center justify-between gap-2">
            <span>{t('chat.autoCompactBanner')}</span>
            <button
              onClick={() => sessionId && void compact(sessionId)}
              className="underline hover:no-underline shrink-0"
            >
              {t('chat.compactNow')}
            </button>
          </div>
        )}

        {(isEmpty && sessionId) || (!sessionId && draft) ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-claude-orange text-white text-lg font-semibold mb-4">
              O
            </div>
            <div className="text-[22px] font-medium text-claude-text mb-1">
              What can I help with today?
            </div>
            <div className="text-[14px] text-claude-textDim mb-5">
              Pick a model below, then type your first message.
            </div>
            {(currentSession || draft) && (
              <ModelPicker
                value={
                  currentSession
                    ? {
                        provider: currentSession.provider,
                        model: currentSession.model,
                      }
                    : draft!
                }
                catalog={catalog}
                onChange={onModelChange}
              />
            )}
          </div>
        ) : (
          <MessageList
            key={sessionId ?? 'none'}
            entries={flow.entries}
            pendingPermissions={ws.pendingPermissions}
            pendingQuestions={ws.pendingQuestions}
            answeredQuestions={ws.answeredQuestions}
            liveAssistant={flow.liveAssistant}
            liveThinking={flow.liveThinking}
            onPermissionDecide={ws.answerPermission}
            onQuestionAnswer={ws.answerQuestion}
          />
        )}

        {ws.followUps.length > 0 && !flow.inFlight && (
          <div className="flex flex-wrap gap-2 px-5 pb-2">
            {ws.followUps.map((s, i) => (
              <button
                key={i}
                onClick={() => send(s, [])}
                className="px-2.5 py-1 rounded-full border border-claude-border text-[12px] text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        <InputBox
          // 連線抖動時(connecting / reconnecting)仍允許打字 — useWebSocket 會把
          // send queue 起來,open 時 flush。只有真的 closed (token 失效 / 重試耗盡)
          // 或已知 inFlight 才 disable。draft 模式無 sessionId 但允許輸入。
          disabled={
            (!sessionId && !draft) || ws.status === 'closed' || flow.inFlight
          }
          onSend={send}
          onAbort={ws.abort}
        />
      </main>
      {showPanel && sessionId && (
        <RightPanel
          sessionId={sessionId}
          events={ws.events}
          refreshKey={turnCount}
        />
      )}
      {planStatus === 'awaiting_approval' && (
        <PlanApprovalModal
          content={planContent}
          onApprove={() => void planAction('approve')}
          onReject={() => void planAction('reject')}
        />
      )}
    </div>
  )
}
