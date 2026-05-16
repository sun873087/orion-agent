import { useEffect, useState } from 'react'
import { ArrowLeft, Plus, Trash2 } from 'lucide-react'

import {
  deleteMemory,
  getMemory,
  listMemories,
  writeMemory,
  type Memory,
  type MemoryListItem,
  type MemoryType,
} from '../../api/agent'
import { useTranslation } from '../../i18n'

const TYPES: MemoryType[] = ['user', 'feedback', 'project', 'reference']

export function MemorySection() {
  const { t } = useTranslation()
  const [memDir, setMemDir] = useState('')
  const [items, setItems] = useState<MemoryListItem[]>([])
  const [editing, setEditing] = useState<Memory | 'new' | null>(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      const r = await listMemories()
      setMemDir(r.memory_dir)
      setItems(r.memories)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function openItem(filename: string) {
    const m = await getMemory(filename)
    if (m) setEditing(m)
  }

  async function handleDelete(filename: string) {
    if (!window.confirm(t('memory.deleteConfirm'))) return
    await deleteMemory(filename)
    await refresh()
  }

  if (editing !== null) {
    return (
      <MemoryEditor
        memory={editing === 'new' ? null : editing}
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
          {t('memory.dirLabel')}{' '}
          <code className="font-mono text-fg-muted">{memDir}</code>
        </div>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
        >
          <Plus size={12} />
          <span>{t('memory.new')}</span>
        </button>
      </div>

      {loading && items.length === 0 ? (
        <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-bg-hover p-6 text-center text-xs text-fg-subtle">
          {t('memory.empty')}
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((m) => (
            <li
              key={m.filename}
              className="flex items-start gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2"
            >
              <button
                type="button"
                onClick={() => openItem(m.filename)}
                className="flex flex-1 flex-col items-start gap-0.5 text-left"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-fg-base">{m.name}</span>
                  {m.type && (
                    <span className="rounded bg-bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                      {m.type}
                    </span>
                  )}
                  {m.expires_at && (
                    <span className="font-mono text-[10px] text-warning">
                      ⏳ {m.expires_at}
                    </span>
                  )}
                </div>
                <span className="text-xs text-fg-muted">{m.description}</span>
                <span className="font-mono text-[10px] text-fg-subtle">{m.filename}</span>
              </button>
              <button
                type="button"
                onClick={() => handleDelete(m.filename)}
                className="rounded p-1 text-fg-muted hover:bg-error/20 hover:text-error"
                title={t('memory.delete')}
              >
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MemoryEditor({
  memory,
  onClose,
  onSaved,
}: {
  memory: Memory | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(memory?.name ?? '')
  const [description, setDescription] = useState(memory?.description ?? '')
  const [type, setType] = useState<MemoryType>((memory?.type as MemoryType) ?? 'user')
  const [body, setBody] = useState(memory?.body ?? '')
  const [expires, setExpires] = useState(memory?.expires_at ?? '')
  const [busy, setBusy] = useState(false)

  const canSave = name.trim() && description.trim() && body.trim()

  async function handleSave() {
    if (!canSave || busy) return
    setBusy(true)
    try {
      await writeMemory({
        filename: memory?.filename ?? null,
        name: name.trim(),
        description: description.trim(),
        type,
        body,
        expires_at: expires.trim() || null,
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
        <Field label={t('memory.field.name')}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('memory.field.namePlaceholder')}
            className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </Field>
        <Field label={t('memory.field.description')}>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('memory.field.descriptionPlaceholder')}
            className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('memory.field.type')}>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as MemoryType)}
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label={t('memory.field.expires')}
            hint={t('memory.field.expiresHint')}
          >
            <input
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
              placeholder="2026-12-31"
              className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </Field>
        </div>
        <Field label={t('memory.field.body')} hint={t('memory.field.bodyHint')}>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={10}
            className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </Field>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm text-fg-muted hover:bg-bg-hover"
          >
            {t('project.cancel')}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave || busy}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('memory.save')}
          </button>
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
