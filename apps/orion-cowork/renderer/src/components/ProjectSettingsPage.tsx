/**
 * 全頁 Project 設定 — 跟 SettingsPage 同 pattern,但 scope=project。
 *
 * 左 categories(General / Skills / Memory / MCP)+ 右 content。
 * General 顯 name / description / instructions / workspace path + 刪除按鈕。
 * 其他三個 reuse user-level sections,prop projectId 切目錄。
 */
import { useEffect, useState } from 'react'
import { ArrowLeft, Brain, Folder, type LucideIcon, Plug, Sparkles, Trash2 } from 'lucide-react'

import {
  deleteProject,
  getProject,
  updateProject,
  type Project,
} from '../api/agent'
import { useTranslation } from '../i18n'
import { useReloadProjects } from '../hooks/useProjects'
import { useSettingsStore } from '../store/settings'

import { McpSection } from './settings/McpSection'
import { MemorySection } from './settings/MemorySection'
import { SkillsSection } from './settings/SkillsSection'

type SectionDef = {
  id: string
  labelKey: string
  icon: LucideIcon
}

const SECTIONS: SectionDef[] = [
  { id: 'general', labelKey: 'projectSettings.section.general', icon: Folder },
  { id: 'skills', labelKey: 'projectSettings.section.skills', icon: Sparkles },
  { id: 'memory', labelKey: 'projectSettings.section.memory', icon: Brain },
  { id: 'mcp', labelKey: 'projectSettings.section.mcp', icon: Plug },
]

export function ProjectSettingsPage() {
  const { t } = useTranslation()
  const editingId = useSettingsStore((s) => s.editingProjectId)
  const close = useSettingsStore((s) => s.closeEditProject)
  const [project, setProject] = useState<Project | null>(null)
  const [active, setActive] = useState('general')

  useEffect(() => {
    if (!editingId) {
      setProject(null)
      return
    }
    getProject(editingId).then((r) => {
      if (r) setProject(r.project)
    })
  }, [editingId])

  if (!editingId) return null
  if (!project) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-bg-base text-sm text-fg-muted">
        {t('settings.mcp.loading')}
      </div>
    )
  }

  const isMac =
    typeof navigator !== 'undefined' && /Mac|iPhone|iPod|iPad/.test(navigator.platform)

  return (
    <div className="flex h-full w-full flex-col bg-bg-base">
      <header
        className={`app-drag flex h-12 shrink-0 items-center gap-3 border-b border-bg-hover ${
          isMac ? 'pl-20 pr-4' : 'px-4'
        }`}
      >
        <button
          type="button"
          onClick={close}
          title={t('settings.back')}
          className="app-no-drag rounded p-1.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <ArrowLeft size={16} />
        </button>
        <h1 className="app-no-drag text-sm font-semibold">
          {t('projectSettings.title', { name: project.name })}
        </h1>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <aside className="scrollbar-thin w-64 shrink-0 overflow-y-auto border-r border-bg-hover bg-bg-panel py-4">
          <ul className="flex flex-col gap-0.5 px-3">
            {SECTIONS.map((s) => {
              const Icon = s.icon
              const isActive = s.id === active
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setActive(s.id)}
                    className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? 'bg-bg-hover text-fg-base'
                        : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
                    }`}
                  >
                    <Icon size={14} />
                    <span>{t(s.labelKey)}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </aside>
        <main className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-3xl">
            {active === 'general' && (
              <GeneralPanel project={project} onUpdated={setProject} onClosed={close} />
            )}
            {active === 'skills' && (
              <>
                <h2 className="mb-4 text-lg font-semibold">{t('projectSettings.section.skills')}</h2>
                <SkillsSection projectId={project.id} />
              </>
            )}
            {active === 'memory' && (
              <>
                <h2 className="mb-4 text-lg font-semibold">{t('projectSettings.section.memory')}</h2>
                <MemorySection projectId={project.id} />
              </>
            )}
            {active === 'mcp' && (
              <>
                <h2 className="mb-4 text-lg font-semibold">{t('projectSettings.section.mcp')}</h2>
                <McpSection projectId={project.id} />
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}

function GeneralPanel({
  project,
  onUpdated,
  onClosed,
}: {
  project: Project
  onUpdated: (p: Project) => void
  onClosed: () => void
}) {
  const { t } = useTranslation()
  const reload = useReloadProjects()
  const setActiveProjectId = useSettingsStore((s) => s.setActiveProjectId)
  const activeProjectId = useSettingsStore((s) => s.activeProjectId)
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [instructions, setInstructions] = useState(project.custom_instructions ?? '')
  const [busy, setBusy] = useState(false)

  async function handleSave() {
    if (!name.trim() || busy) return
    setBusy(true)
    try {
      await updateProject(project.id, {
        name: name.trim(),
        description: description.trim() || null,
        custom_instructions: instructions || null,
      })
      onUpdated({
        ...project,
        name: name.trim(),
        description: description.trim() || null,
        custom_instructions: instructions || null,
      })
      await reload()
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm(t('projectSettings.deleteConfirm', { name: project.name }))) return
    setBusy(true)
    try {
      await deleteProject(project.id)
      if (activeProjectId === project.id) setActiveProjectId(null)
      await reload()
      onClosed()
    } finally {
      setBusy(false)
    }
  }

  const ws = project.workspace_dir ?? ''
  const cowork = ws ? `${ws}/.orion-cowork` : ''

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">{t('projectSettings.section.general')}</h2>
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
          rows={8}
          className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </Field>
      <div className="flex items-center justify-between border-t border-bg-hover pt-4">
        <button
          type="button"
          onClick={handleDelete}
          disabled={busy}
          className="flex items-center gap-1 rounded-md px-3 py-1.5 text-sm text-error hover:bg-error/10"
        >
          <Trash2 size={12} />
          <span>{t('projectSettings.delete')}</span>
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
