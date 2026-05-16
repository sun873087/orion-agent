import { useState } from 'react'
import { Folder, X } from 'lucide-react'

import { createProject } from '../api/agent'
import { useTranslation } from '../i18n'
import { useSettingsStore } from '../store/settings'
import { useReloadProjects } from '../hooks/useProjects'

export function NewProjectModal() {
  const { t } = useTranslation()
  const open = useSettingsStore((s) => s.newProjectOpen)
  const close = useSettingsStore((s) => s.closeNewProject)
  const reload = useReloadProjects()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [workspaceDir, setWorkspaceDir] = useState<string | null>(null)
  const [instructions, setInstructions] = useState('')
  const [busy, setBusy] = useState(false)

  if (!open) return null

  function reset() {
    setName('')
    setDescription('')
    setWorkspaceDir(null)
    setInstructions('')
  }

  async function pickFolder() {
    const path = await window.dialog.selectFolder()
    if (path) setWorkspaceDir(path)
  }

  async function submit() {
    if (!name.trim() || !workspaceDir || busy) return
    setBusy(true)
    try {
      await createProject({
        name: name.trim(),
        description: description.trim() || null,
        workspace_dir: workspaceDir,
        custom_instructions: instructions.trim() || null,
      })
      await reload()
      reset()
      close()
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = !!name.trim() && !!workspaceDir && !busy

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={close}
    >
      <div
        className="flex w-full max-w-lg flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="text-sm font-semibold">{t('project.modal.title')}</h2>
          <button
            type="button"
            onClick={close}
            className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex flex-col gap-4 px-5 py-4">
          <Field label={t('project.field.name')}>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('project.field.namePlaceholder')}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>
          <Field label={t('project.field.description')}>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('project.field.descriptionPlaceholder')}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>
          <Field
            label={`${t('project.field.workspace')} *`}
            hint={t('project.field.workspaceHint')}
          >
            <button
              type="button"
              onClick={pickFolder}
              className="flex w-full items-center justify-between gap-2 rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm hover:bg-bg-hover"
            >
              <span className="flex items-center gap-2 truncate">
                <Folder size={14} className="shrink-0 text-fg-muted" />
                <span className="truncate">
                  {workspaceDir || (
                    <span className="text-fg-subtle">{t('project.field.noFolder')}</span>
                  )}
                </span>
              </span>
              <span className="shrink-0 text-xs text-fg-subtle">
                {t('project.field.selectFolder')}
              </span>
            </button>
          </Field>
          <Field label={t('project.field.instructions')}>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder={t('project.field.instructionsPlaceholder')}
              rows={3}
              className="w-full resize-none rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
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
            {t('project.cancel')}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('project.create')}
          </button>
        </footer>
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-fg-muted">{label}</label>
      {children}
      {hint && <span className="text-[11px] text-fg-subtle">{hint}</span>}
    </div>
  )
}
