import { useEffect, useState } from 'react'
import { ArrowLeft, Lock, Plus, Trash2 } from 'lucide-react'

import {
  deleteSkill,
  getSkill,
  listSkills,
  writeSkill,
  type Skill,
  type SkillListItem,
} from '../../api/agent'
import { useTranslation } from '../../i18n'

const SOURCE_COLOR: Record<string, string> = {
  bundled: 'text-fg-muted',
  system: 'text-accent',
  user: 'text-success',
  other: 'text-fg-subtle',
  unknown: 'text-fg-subtle',
}

export function SkillsSection({ projectId }: { projectId?: string | null } = {}) {
  const { t } = useTranslation()
  const [items, setItems] = useState<SkillListItem[]>([])
  const [userDir, setUserDir] = useState('')
  const [editing, setEditing] = useState<Skill | 'new' | null>(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      const r = await listSkills(projectId ?? null)
      setItems(r.skills)
      setUserDir(r.user_skills_dir)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [projectId])

  async function openItem(name: string) {
    const s = await getSkill(name, projectId ?? null)
    if (s) setEditing(s)
  }

  async function handleDelete(s: SkillListItem) {
    // project scope:project 內所有 skill 都可刪;user scope:只 editable
    if (!projectId && !s.editable) return
    if (!window.confirm(t('skill.deleteConfirm', { name: s.name }))) return
    await deleteSkill(s.filename, projectId ?? null)
    await refresh()
  }

  if (editing !== null) {
    return (
      <SkillEditor
        skill={editing === 'new' ? null : editing}
        projectId={projectId ?? null}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null)
          await refresh()
        }}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-fg-subtle">
          {t('skill.userDirLabel')}{' '}
          <code className="font-mono text-fg-muted">{userDir}</code>
        </div>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
        >
          <Plus size={12} />
          <span>{t('skill.new')}</span>
        </button>
      </div>

      {loading && items.length === 0 ? (
        <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-bg-hover p-6 text-center text-xs text-fg-subtle">
          {t('skill.empty')}
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((s) => (
            <li
              key={s.name}
              className="flex items-start gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2"
            >
              <button
                type="button"
                onClick={() => openItem(s.name)}
                className="flex flex-1 flex-col items-start gap-0.5 text-left"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-fg-base">{s.name}</span>
                  <span
                    className={`rounded bg-bg-hover px-1.5 py-0.5 font-mono text-[10px] ${
                      SOURCE_COLOR[s.source] ?? 'text-fg-muted'
                    }`}
                  >
                    {s.source}
                  </span>
                  {!s.editable && <Lock size={10} className="text-fg-subtle" />}
                </div>
                <span className="text-xs text-fg-muted">{s.description}</span>
              </button>
              {s.editable && (
                <button
                  type="button"
                  onClick={() => handleDelete(s)}
                  className="rounded p-1 text-fg-muted hover:bg-error/20 hover:text-error"
                  title={t('skill.delete')}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SkillEditor({
  skill,
  projectId,
  onClose,
  onSaved,
}: {
  skill: Skill | null
  projectId?: string | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { t } = useTranslation()
  // project scope 內所有 skill 都可改;user scope 仰賴 editable 旗標
  const readonly = skill !== null && !projectId && !skill.editable
  const [name, setName] = useState(skill?.name ?? '')
  const [description, setDescription] = useState(skill?.description ?? '')
  const [body, setBody] = useState(skill?.body ?? '')
  const [busy, setBusy] = useState(false)

  const canSave = !readonly && name.trim() && description.trim() && body.trim()

  async function handleSave() {
    if (!canSave || busy) return
    setBusy(true)
    try {
      await writeSkill({
        filename: skill?.filename ?? null,
        name: name.trim(),
        description: description.trim(),
        body,
        rename_from: skill && (projectId || skill.editable) ? skill.filename : null,
        project_id: projectId ?? null,
      })
      await onSaved()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        onClick={onClose}
        className="flex w-fit items-center gap-1 text-xs text-fg-muted hover:text-fg-base"
      >
        <ArrowLeft size={12} />
        <span>{t('memory.backToList')}</span>
      </button>

      <div className="flex flex-col gap-3 rounded-lg border border-bg-hover bg-bg-panel p-4">
        {readonly && (
          <div className="flex items-center gap-2 rounded-md border border-bg-hover bg-bg-input px-3 py-2 text-xs text-fg-muted">
            <Lock size={12} />
            <span>
              {t('skill.readonly', { source: skill?.source ?? '' })}
            </span>
          </div>
        )}
        <Field label={t('skill.field.name')}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            readOnly={readonly}
            placeholder={t('skill.field.namePlaceholder')}
            className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent read-only:opacity-70"
          />
        </Field>
        <Field label={t('skill.field.description')}>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            readOnly={readonly}
            placeholder={t('skill.field.descriptionPlaceholder')}
            className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent read-only:opacity-70"
          />
        </Field>
        <Field label={t('skill.field.body')} hint={t('skill.field.bodyHint')}>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            readOnly={readonly}
            rows={16}
            className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-accent read-only:opacity-70"
          />
        </Field>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm text-fg-muted hover:bg-bg-hover"
          >
            {readonly ? t('memory.backToList') : t('project.cancel')}
          </button>
          {!readonly && (
            <button
              type="button"
              onClick={handleSave}
              disabled={!canSave || busy}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('memory.save')}
            </button>
          )}
        </div>
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
