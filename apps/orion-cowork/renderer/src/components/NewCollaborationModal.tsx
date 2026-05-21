import { useState } from 'react'
import { Folder, X } from 'lucide-react'

import { createCollaboration, listCollaborations } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

export function NewCollaborationModal() {
  const { t } = useTranslation()
  const open = useSettingsStore((s) => s.newCollabOpen)
  const close = useSettingsStore((s) => s.closeNewCollab)
  const setCollaborations = useAgentStore((s) => s.setCollaborations)
  const openCollab = useAgentStore((s) => s.openCollaboration)

  const [name, setName] = useState('')
  const [workspaceDir, setWorkspaceDir] = useState<string | null>(null)
  const [budget, setBudget] = useState('')
  const [busy, setBusy] = useState(false)

  if (!open) return null

  function reset() {
    setName('')
    setWorkspaceDir(null)
    setBudget('')
  }

  async function pickFolder() {
    const path = await window.dialog.selectFolder()
    if (path) setWorkspaceDir(path)
  }

  async function submit() {
    if (!name.trim() || busy) return
    setBusy(true)
    try {
      const budgetNum = budget.trim() ? parseFloat(budget) : null
      const created = await createCollaboration({
        name: name.trim(),
        workspace_dir: workspaceDir || null,
        budget_usd_cap: budgetNum && budgetNum > 0 ? budgetNum : null,
      })
      // 重 load list + 開新 collab
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
      openCollab(created.collaboration.id)
      reset()
      close()
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = !!name.trim() && !busy

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
          <h2 className="text-sm font-semibold">{t('collab.modal.title')}</h2>
          <button
            type="button"
            onClick={close}
            className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex flex-col gap-4 px-5 py-4">
          <Field label={t('collab.modal.name')}>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('collab.modal.namePlaceholder')}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>
          <Field label={t('collab.modal.workspace')}>
            <button
              type="button"
              onClick={pickFolder}
              className="flex w-full items-center justify-between gap-2 rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm hover:bg-bg-hover"
            >
              <span className="flex items-center gap-2 truncate">
                <Folder size={14} className="shrink-0 text-fg-muted" />
                <span className="truncate">
                  {workspaceDir || (
                    <span className="text-fg-subtle">—</span>
                  )}
                </span>
              </span>
              <span className="shrink-0 text-xs text-fg-subtle">…</span>
            </button>
          </Field>
          <Field label={t('collab.modal.budget')}>
            <input
              type="number"
              step="0.01"
              min="0"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="0.00"
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            />
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
            {t('collab.modal.create')}
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
