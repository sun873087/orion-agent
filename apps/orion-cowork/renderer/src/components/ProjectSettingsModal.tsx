import { useEffect, useState } from 'react'
import { Folder, Trash2, X } from 'lucide-react'

import {
  deleteProject,
  getProject,
  updateProject,
  type Project,
} from '../api/agent'
import { useTranslation } from '../i18n'
import { useReloadProjects } from '../hooks/useProjects'
import { useSettingsStore } from '../store/settings'

/**
 * Project 設定 modal:編輯 name / description / instructions,顯 workspace
 * + co-located paths(skills / memory / mcp 唯讀提示),可刪 project。
 */
export function ProjectSettingsModal() {
  const { t } = useTranslation()
  const editingId = useSettingsStore((s) => s.editingProjectId)
  const close = useSettingsStore((s) => s.closeEditProject)
  const activeProjectId = useSettingsStore((s) => s.activeProjectId)
  const setActiveProjectId = useSettingsStore((s) => s.setActiveProjectId)
  const reload = useReloadProjects()
  const [project, setProject] = useState<Project | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!editingId) {
      setProject(null)
      return
    }
    getProject(editingId).then((r) => {
      if (!r) return
      setProject(r.project)
      setName(r.project.name)
      setDescription(r.project.description ?? '')
      setInstructions(r.project.custom_instructions ?? '')
    })
  }, [editingId])

  if (!editingId || !project) return null
  const proj = project  // type narrow

  async function handleSave() {
    if (!name.trim() || busy) return
    setBusy(true)
    try {
      await updateProject(proj.id, {
        name: name.trim(),
        description: description.trim() || null,
        custom_instructions: instructions || null,
      })
      await reload()
      close()
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm(t('projectSettings.deleteConfirm', { name: proj.name }))) return
    setBusy(true)
    try {
      await deleteProject(proj.id)
      if (activeProjectId === proj.id) setActiveProjectId(null)
      await reload()
      close()
    } finally {
      setBusy(false)
    }
  }

  const ws = project.workspace_dir ?? ''
  const cowork = ws ? `${ws}/.orion-cowork` : ''

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={close}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="text-sm font-semibold">
            {t('projectSettings.title', { name: project.name })}
          </h2>
          <button
            type="button"
            onClick={close}
            className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            <X size={16} />
          </button>
        </header>
        <div className="scrollbar-thin flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          <Field label={t('project.field.name')}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>
          <Field label={t('project.field.description')}>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>
          <Field label={t('project.field.workspace')} hint={t('projectSettings.workspaceHint')}>
            <div className="flex items-center gap-2 rounded-md border border-bg-hover bg-bg-panel px-3 py-1.5">
              <Folder size={14} className="text-fg-muted" />
              <span className="flex-1 truncate font-mono text-xs text-fg-base">{ws}</span>
            </div>
          </Field>
          <Field
            label={t('project.field.instructions')}
            hint={t('projectSettings.instructionsHint', { path: `${cowork}/instructions.md` })}
          >
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={6}
              className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>

          <div className="rounded-lg border border-bg-hover bg-bg-panel p-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
              {t('projectSettings.resourcesTitle')}
            </div>
            <ResourceRow label={t('projectSettings.skillsPath')} path={`${cowork}/skills/`} />
            <ResourceRow label={t('projectSettings.memoryPath')} path={`${cowork}/memory/`} />
            <ResourceRow label={t('projectSettings.mcpPath')} path={`${cowork}/mcp.json`} />
            <p className="mt-2 text-[11px] text-fg-subtle">
              {t('projectSettings.resourcesHint')}
            </p>
          </div>
        </div>
        <footer className="flex items-center justify-between gap-2 border-t border-bg-hover px-5 py-3">
          <button
            type="button"
            onClick={handleDelete}
            disabled={busy}
            className="flex items-center gap-1 rounded-md px-3 py-1.5 text-sm text-error hover:bg-error/10"
          >
            <Trash2 size={12} />
            <span>{t('projectSettings.delete')}</span>
          </button>
          <div className="flex gap-2">
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
              onClick={handleSave}
              disabled={busy || !name.trim()}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('memory.save')}
            </button>
          </div>
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

function ResourceRow({ label, path }: { label: string; path: string }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1">
      <span className="text-xs text-fg-muted">{label}</span>
      <code className="truncate font-mono text-[10px] text-fg-subtle" title={path}>
        {path}
      </code>
    </div>
  )
}
