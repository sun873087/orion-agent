import { useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'

import {
  addPaneToCollaboration,
  createConversation,
  fetchModels,
  getCollaboration,
  listCollaborations,
  type ModelCatalog,
} from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

const PANE_ROLES = ['researcher', 'coder', 'reviewer', 'doc-writer', 'custom'] as const

export function AddPaneModal() {
  const { t } = useTranslation()
  const targetCollabId = useSettingsStore((s) => s.addPaneTargetCollabId)
  const close = useSettingsStore((s) => s.closeAddPane)
  const setCollaborations = useAgentStore((s) => s.setCollaborations)
  const defaultProvider = useSettingsStore((s) => s.selectedProvider)
  const defaultModel = useSettingsStore((s) => s.selectedModel)

  const [paneName, setPaneName] = useState('')
  const [paneRole, setPaneRole] = useState<typeof PANE_ROLES[number]>('coder')
  const [provider, setProvider] = useState(defaultProvider)
  const [model, setModel] = useState(defaultModel)
  const [busy, setBusy] = useState(false)
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null)

  useEffect(() => {
    if (!targetCollabId) return
    void (async () => {
      try {
        setCatalog(await fetchModels())
      } catch {
        // 失敗則保留 defaultProvider/Model 不更
      }
    })()
  }, [targetCollabId])

  const providers = catalog?.providers ?? []
  const currentProvider = useMemo(
    () => providers.find((p) => p.id === provider) ?? providers[0],
    [providers, provider],
  )
  const models = currentProvider?.models ?? []

  if (!targetCollabId) return null

  async function submit() {
    if (!targetCollabId || !paneName.trim() || busy) return
    setBusy(true)
    try {
      // 1. 建新 conversation
      const sessionId = await createConversation(provider, model)
      // 2. 加進 collab
      const cleanName = paneName.trim().startsWith('@')
        ? paneName.trim()
        : `@${paneName.trim()}`
      await addPaneToCollaboration({
        collaboration_id: targetCollabId,
        session_id: sessionId,
        pane_name: cleanName,
        pane_role: paneRole,
      })
      // 3. 重 load collab — 同時讓 MultiPaneView re-fetch
      const items = await listCollaborations()
      setCollaborations(items.map((v) => ({
        id: v.collaboration.id,
        name: v.collaboration.name,
        workspace_dir: v.collaboration.workspace_dir,
        project_id: v.collaboration.project_id,
        budget_usd_cap: v.collaboration.budget_usd_cap,
        panes: v.panes.map((p) => ({
          session_id: p.session_id,
          pane_name: p.pane_name,
          pane_role: p.pane_role,
          pane_position: p.pane_position,
        })),
      })))
      // 通知 MultiPaneView reload(透過 read 一次,觸發 effect)
      await getCollaboration(targetCollabId)
      setPaneName('')
      close()
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = !!paneName.trim() && !busy

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={close}
    >
      <div
        className="flex w-full max-w-md flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="text-sm font-semibold">{t('collab.addPane.title')}</h2>
          <button
            type="button"
            onClick={close}
            className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex flex-col gap-4 px-5 py-4">
          <Field label={t('collab.addPane.paneName')}>
            <input
              autoFocus
              value={paneName}
              onChange={(e) => setPaneName(e.target.value)}
              placeholder="@backend"
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>
          <Field label={t('collab.addPane.role')}>
            <select
              value={paneRole}
              onChange={(e) => setPaneRole(e.target.value as typeof PANE_ROLES[number])}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {PANE_ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </Field>
          <Field label={t('collab.addPane.provider')}>
            <select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value)
                // 切 provider 時也順帶切第一個 model
                const next = providers.find((p) => p.id === e.target.value)
                if (next && next.models.length > 0) {
                  setModel(next.models[0].id)
                }
              }}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </Field>
          <Field label={t('collab.addPane.model')}>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.label || m.id}</option>
              ))}
            </select>
          </Field>
        </div>
        <footer className="flex justify-end gap-2 border-t border-bg-hover px-5 py-3">
          <button
            type="button"
            onClick={close}
            disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm text-fg-muted hover:bg-bg-hover"
          >
            {t('collab.modal.cancel')}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('collab.addPane.add')}
          </button>
        </footer>
      </div>
    </div>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-fg-muted">{label}</label>
      {children}
    </div>
  )
}
