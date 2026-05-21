import { useEffect, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Group, Panel, Separator } from 'react-resizable-panels'

import {
  getCollaboration,
  getCollaborationCostSummary,
  removePaneFromCollaboration,
  type CollaborationCostSummary,
  type CollaborationView,
} from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'
import type { Message } from '../store/agent'
import { useSettingsStore } from '../store/settings'

// 穩定 reference — 避免 Zustand selector 每次回傳 new [] 觸發 infinite re-render
const EMPTY_MESSAGES: Message[] = []

/** Render multi-pane collaboration view — N session 並排顯示,
 *  user 點 pane 切焦點(全域 sessionId 同步改),InputBox 送到焦點 pane。
 *  Resize 由 react-resizable-panels 處理(layout 不持久化,刷頁面回 50/50)。
 */
export function MultiPaneView() {
  const { t } = useTranslation()
  const collaborationId = useAgentStore((s) => s.currentCollaborationId)
  const activeIndex = useAgentStore((s) => s.activeCollabPaneIndex)
  const setActiveIndex = useAgentStore((s) => s.setActiveCollabPaneIndex)
  const setSessionId = useAgentStore((s) => s.setSessionId)
  const openCollaboration = useAgentStore((s) => s.openCollaboration)
  const collaborations = useAgentStore((s) => s.collaborations)
  const openAddPane = useSettingsStore((s) => s.openAddPane)

  const [view, setView] = useState<CollaborationView | null>(null)
  const [costSummary, setCostSummary] = useState<CollaborationCostSummary | null>(null)
  const [loading, setLoading] = useState(true)
  // collaborations 列表變了(add_pane 完成 → setCollaborations)→ 重撈 view
  const collabSig = collaborations.find((c) => c.id === collaborationId)?.panes.length ?? 0

  useEffect(() => {
    if (!collaborationId) return
    let cancelled = false
    setLoading(true)
    void (async () => {
      try {
        const v = await getCollaboration(collaborationId)
        if (!cancelled) setView(v)
        const c = await getCollaborationCostSummary(collaborationId)
        if (!cancelled) setCostSummary(c)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [collaborationId, collabSig])

  // 切 active pane 時把 global sessionId 同步,讓既有 InputBox 送到對的 session。
  useEffect(() => {
    if (!view) return
    const panes = view.panes
    if (panes.length === 0) return
    const idx = activeIndex ?? 0
    const pane = panes[Math.min(idx, panes.length - 1)]
    if (pane) setSessionId(pane.session_id)
  }, [view, activeIndex, setSessionId])

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center text-fg-muted">
        <span className="text-sm">{t('collab.loading')}</span>
      </div>
    )
  }
  if (!view) {
    return (
      <div className="flex h-full w-full items-center justify-center text-fg-muted">
        <span className="text-sm">{t('collab.notFound')}</span>
      </div>
    )
  }
  const panes = view.panes
  if (panes.length === 0) {
    return (
      <div className="flex h-full w-full flex-col overflow-hidden">
        <CollabHeader
          name={view.collaboration.name}
          paneCount={0}
          totalCost={costSummary?.total_cost_usd ?? 0}
          onAddPane={() => collaborationId && openAddPane(collaborationId)}
          onClose={() => openCollaboration(null)}
        />
        <div className="flex flex-1 items-center justify-center p-6 text-sm text-fg-muted">
          <div className="max-w-md text-center">
            {t('collab.empty.title')}
            <div className="mt-2 text-xs">{t('collab.empty.hint')}</div>
            <button
              type="button"
              onClick={() => collaborationId && openAddPane(collaborationId)}
              className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
            >
              <Plus size={12} />
              {t('collab.header.addPane')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <CollabHeader
        name={view.collaboration.name}
        paneCount={panes.length}
        totalCost={costSummary?.total_cost_usd ?? 0}
        onAddPane={() => collaborationId && openAddPane(collaborationId)}
        onClose={() => openCollaboration(null)}
      />
      <Group orientation="horizontal" className="flex-1">
        {panes.map((pane, idx) => {
          const isLast = idx === panes.length - 1
          const isActive = (activeIndex ?? 0) === idx
          const paneCost = costSummary?.panes.find((p) => p.session_id === pane.session_id)
          return (
            <PanelGroupSegment
              key={pane.session_id}
              isLast={isLast}
              isActive={isActive}
              onActivate={() => setActiveIndex(idx)}
              paneName={pane.pane_name}
              paneRole={pane.pane_role}
              sessionId={pane.session_id}
              cost={paneCost}
            />
          )
        })}
      </Group>
    </div>
  )
}

function CollabHeader({
  name,
  paneCount,
  totalCost,
  onAddPane,
  onClose,
}: {
  name: string
  paneCount: number
  totalCost: number
  onAddPane: () => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-2 border-b border-bg-hover bg-bg-elevated px-3 py-2 text-xs">
      <span className="font-medium text-fg-base">{name}</span>
      <span className="text-fg-muted">
        {t('collab.header.paneCount', { n: paneCount })}
      </span>
      <span className="ml-1 text-fg-muted">${totalCost.toFixed(4)}</span>
      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={onAddPane}
          title={t('collab.header.addPane')}
          className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <Plus size={14} />
        </button>
        <button
          type="button"
          onClick={onClose}
          title={t('collab.header.close')}
          className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}

function PanelGroupSegment({
  isLast,
  isActive,
  onActivate,
  paneName,
  paneRole,
  sessionId,
  cost,
}: {
  isLast: boolean
  isActive: boolean
  onActivate: () => void
  paneName: string
  paneRole: string | null
  sessionId: string
  cost?: {
    model: string | null
    input_tokens: number
    output_tokens: number
    cost_usd: number
  } | undefined
}) {
  return (
    <>
      <Panel minSize="20%" defaultSize="50%">
        <PaneContent
          isActive={isActive}
          onActivate={onActivate}
          paneName={paneName}
          paneRole={paneRole}
          sessionId={sessionId}
          cost={cost}
        />
      </Panel>
      {!isLast && (
        <Separator className="w-px bg-bg-hover transition-colors hover:bg-accent/50" />
      )}
    </>
  )
}

function PaneContent({
  isActive,
  onActivate,
  paneName,
  paneRole,
  sessionId,
  cost,
}: {
  isActive: boolean
  onActivate: () => void
  paneName: string
  paneRole: string | null
  sessionId: string
  cost?: {
    model: string | null
    input_tokens: number
    output_tokens: number
    cost_usd: number
  } | undefined
}) {
  const messages = useAgentStore((s) => s.messagesBySession[sessionId] ?? EMPTY_MESSAGES)
  const busy = useAgentStore((s) => s.busyBySession[sessionId] ?? false)
  const error = useAgentStore((s) => s.errorBySession[sessionId] ?? null)

  const borderCls = isActive
    ? 'border-accent ring-1 ring-accent/30'
    : 'border-bg-hover'

  return (
    <div
      role="region"
      tabIndex={0}
      onClick={onActivate}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onActivate()
      }}
      className={`flex h-full cursor-pointer flex-col overflow-hidden border-l-2 transition-colors ${borderCls}`}
    >
      <PaneHeader
        isActive={isActive}
        paneName={paneName}
        paneRole={paneRole}
        busy={busy}
        cost={cost}
        sessionId={sessionId}
      />
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {error && (
          <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-xs text-red-300">
            {error}
          </div>
        )}
        {messages.length === 0 ? (
          <div className="py-8 text-center text-xs text-fg-muted">
            (no messages yet)
          </div>
        ) : (
          <PaneMessagesList messages={messages} />
        )}
      </div>
    </div>
  )
}

function PaneHeader({
  isActive,
  paneName,
  paneRole,
  busy,
  cost,
  sessionId,
}: {
  isActive: boolean
  paneName: string
  paneRole: string | null
  busy: boolean
  cost?: {
    model: string | null
    input_tokens: number
    output_tokens: number
    cost_usd: number
  } | undefined
  sessionId: string
}) {
  const { t } = useTranslation()
  const collaborations = useAgentStore((s) => s.collaborations)
  const setCollaborations = useAgentStore((s) => s.setCollaborations)
  const currentCollabId = useAgentStore((s) => s.currentCollaborationId)
  const statusColor = busy
    ? 'bg-yellow-400'
    : isActive
    ? 'bg-green-400'
    : 'bg-fg-muted/50'

  async function removeThisPane(e: React.MouseEvent) {
    e.stopPropagation()
    if (!currentCollabId) return
    if (!confirm(t('collab.pane.removeConfirm', { name: paneName }))) return
    await removePaneFromCollaboration(sessionId)
    // optimistic store update — 同 collab 移除這 pane
    setCollaborations(collaborations.map((c) =>
      c.id === currentCollabId
        ? { ...c, panes: c.panes.filter((p) => p.session_id !== sessionId) }
        : c,
    ))
  }

  return (
    <div className="flex items-center gap-2 border-b border-bg-hover bg-bg-elevated px-3 py-2 text-xs">
      <span className={`h-2 w-2 rounded-full ${statusColor}`} />
      <span className="font-mono font-medium">{paneName}</span>
      {paneRole && (
        <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-fg-muted">
          {paneRole}
        </span>
      )}
      <div className="ml-auto flex items-center gap-2 text-fg-muted">
        {cost?.model && <span className="text-[10px]">{cost.model}</span>}
        {cost && (
          <span className="text-[10px]">
            ${cost.cost_usd.toFixed(4)}
          </span>
        )}
        <button
          type="button"
          onClick={removeThisPane}
          title={t('collab.pane.removeFromCollab')}
          className="rounded p-0.5 text-fg-muted hover:bg-bg-hover hover:text-red-400"
        >
          <X size={12} />
        </button>
      </div>
    </div>
  )
}

/** 簡化版 message list — collab view 內每 pane 都顯這個。
 *  與主 MessageList 不同的是不接 sidebar / fork / context 等複雜互動,
 *  只 read-only-ish 看 transcript。完整互動只在 active pane (主 InputBox)。 */
function PaneMessagesList({ messages }: { messages: Message[] }) {
  return (
    <div className="flex flex-col gap-2">
      {messages.map((m) => (
        <div
          key={m.id}
          className={
            m.role === 'user'
              ? 'rounded bg-bg-elevated px-2 py-1.5 text-xs'
              : 'px-2 py-1 text-xs text-fg-base'
          }
        >
          <div className="mb-0.5 text-[10px] uppercase text-fg-muted">
            {m.role}
          </div>
          <PaneMessageContent message={m} />
        </div>
      ))}
    </div>
  )
}

function PaneMessageContent({ message }: { message: Message }) {
  // 簡化版:user / system 顯示 text;assistant 走 blocks(text 或 tools 標)
  if (message.role === 'user' || message.role === 'system') {
    return <div className="whitespace-pre-wrap break-words">{message.text ?? ''}</div>
  }
  const blocks = message.blocks ?? []
  if (blocks.length === 0) {
    // 退路:沒 blocks 但有 text(history reload 後)
    return <div className="whitespace-pre-wrap break-words">{message.text ?? ''}</div>
  }
  return (
    <div className="flex flex-col gap-1">
      {blocks.map((b, i) => {
        if (b.type === 'text') {
          return (
            <div key={i} className="whitespace-pre-wrap break-words">
              {b.text}
            </div>
          )
        }
        if (b.type === 'tools') {
          return (
            <div
              key={i}
              className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-fg-muted"
            >
              [tool calls: {b.toolUseIds.length}]
            </div>
          )
        }
        return null
      })}
    </div>
  )
}
