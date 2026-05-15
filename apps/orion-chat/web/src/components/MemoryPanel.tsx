import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'

type MemoryType = 'user' | 'feedback' | 'project' | 'reference'

interface MemorySummary {
  filename: string
  name: string
  description: string
  type: MemoryType | null
}

interface MemoryDetail extends MemorySummary {
  body: string
}

const TYPE_LABEL: Record<MemoryType, string> = {
  user: 'User',
  feedback: 'Feedback',
  project: 'Project',
  reference: 'Reference',
}

const TYPE_COLOR: Record<MemoryType, string> = {
  user: 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300',
  feedback:
    'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300',
  project:
    'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300',
  reference:
    'bg-violet-100 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300',
}

export function MemoryPanel() {
  const [items, setItems] = useState<MemorySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<MemoryDetail | null>(null)
  const [creating, setCreating] = useState(false)

  async function refresh() {
    setError(null)
    try {
      const list = await apiFetch<MemorySummary[]>('/me/memories')
      setItems(list)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function openItem(filename: string) {
    setError(null)
    try {
      const detail = await apiFetch<MemoryDetail>(
        `/me/memories/${encodeURIComponent(filename)}`,
      )
      setEditing(detail)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function deleteItem(filename: string) {
    if (!confirm(`Delete memory "${filename}"?`)) return
    setError(null)
    try {
      await apiFetch(`/me/memories/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="p-6 space-y-4 text-[14px]">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium text-claude-text">Memories</div>
          <div className="text-[12px] text-claude-textDim">
            Persistent notes Orion uses across all conversations. Stored under{' '}
            <code className="font-mono text-[11px] bg-claude-code px-1 py-0.5 rounded">
              ~/.orion/users/&lt;you&gt;/memory/
            </code>
            .
          </div>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 bg-claude-orange hover:bg-claude-orangeHover text-white rounded-md text-[13px] font-medium transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 3v10M3 8h10"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          New
        </button>
      </div>

      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-[13px] text-claude-textDim italic">Loading…</div>
      ) : items.length === 0 ? (
        <div className="text-[13px] text-claude-textFaint italic">
          No memories yet. Create one to give Orion persistent context.
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((m) => (
            <div
              key={m.filename}
              className="group flex items-start gap-3 p-3 rounded-md bg-white dark:bg-claude-panel border border-claude-borderSoft hover:border-claude-border transition-colors cursor-pointer"
              onClick={() => void openItem(m.filename)}
            >
              {m.type && (
                <span
                  className={`shrink-0 text-[11px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide ${TYPE_COLOR[m.type]}`}
                >
                  {TYPE_LABEL[m.type]}
                </span>
              )}
              <div className="flex-1 min-w-0">
                <div className="font-medium text-claude-text truncate">
                  {m.name}
                </div>
                <div className="text-[12px] text-claude-textDim truncate">
                  {m.description}
                </div>
                <div className="text-[11px] text-claude-textFaint font-mono mt-0.5 truncate">
                  {m.filename}
                </div>
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 p-1 text-claude-textFaint hover:text-red-600 transition"
                onClick={(e) => {
                  e.stopPropagation()
                  void deleteItem(m.filename)
                }}
                aria-label="delete"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M4 4l8 8M12 4l-8 8"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <MemoryEditor
          initial={editing}
          mode="edit"
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await refresh()
          }}
        />
      )}
      {creating && (
        <MemoryEditor
          initial={null}
          mode="create"
          onClose={() => setCreating(false)}
          onSaved={async () => {
            setCreating(false)
            await refresh()
          }}
        />
      )}
    </div>
  )
}

interface EditorProps {
  initial: MemoryDetail | null
  mode: 'edit' | 'create'
  onClose: () => void
  onSaved: () => void | Promise<void>
}

function MemoryEditor({ initial, mode, onClose, onSaved }: EditorProps) {
  const [filename, setFilename] = useState(initial?.filename ?? '')
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [type, setType] = useState<MemoryType | ''>(initial?.type ?? '')
  const [body, setBody] = useState(initial?.body ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      let fname = filename.trim()
      if (mode === 'create') {
        if (!fname) {
          // default filename from name
          fname = `${
            name
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, '_')
              .slice(0, 40) || 'memory'
          }.md`
        }
        if (!fname.endsWith('.md')) fname += '.md'
      }
      const payload: Record<string, unknown> = {
        name: name.trim(),
        description: description.trim(),
        body,
      }
      if (type) payload.type = type
      await apiFetch(`/me/memories/${encodeURIComponent(fname)}`, {
        method: 'PUT',
        body: payload,
      })
      await onSaved()
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? `${e.message} (HTTP ${e.status})`
          : e instanceof Error
            ? e.message
            : String(e)
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  const inputCls =
    'w-full border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-claude-cream text-claude-text placeholder:text-claude-textFaint focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-[2px] p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-claude-cream dark:bg-claude-panel rounded-2xl shadow-modal flex flex-col max-h-[85vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-claude-border/60">
          <div className="text-[15px] font-medium">
            {mode === 'create' ? 'New memory' : 'Edit memory'}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
            aria-label="close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M4 4l8 8M12 4l-8 8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <div className="p-5 space-y-3 overflow-y-auto">
          {mode === 'create' && (
            <Field
              label="Filename"
              hint="auto-generated if blank — must end with .md"
            >
              <input
                className={`${inputCls} font-mono`}
                placeholder="user_role.md"
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
              />
            </Field>
          )}
          {mode === 'edit' && (
            <div className="text-[12px] text-claude-textFaint font-mono">
              {filename}
            </div>
          )}
          <Field label="Name" hint="Short title">
            <input
              className={inputCls}
              placeholder="e.g. Likes terse explanations"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </Field>
          <Field
            label="Description"
            hint="One-line summary used by the relevance ranker"
          >
            <input
              className={inputCls}
              placeholder="e.g. user prefers single-paragraph summaries with no headers"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <Field label="Type">
            <select
              value={type}
              onChange={(e) => setType(e.target.value as MemoryType | '')}
              className={inputCls}
            >
              <option value="">— none —</option>
              <option value="user">User</option>
              <option value="feedback">Feedback</option>
              <option value="project">Project</option>
              <option value="reference">Reference</option>
            </select>
          </Field>
          <Field label="Body" hint="Markdown content">
            <textarea
              className={`${inputCls} h-44 font-mono text-[12px] leading-relaxed resize-none`}
              placeholder="Anything Orion should know…"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </Field>
          {error && (
            <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-claude-border/60">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-[13px] text-claude-textDim hover:text-claude-text transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => void save()}
            disabled={busy || !name.trim() || !description.trim()}
            className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
          >
            {busy ? 'Saving…' : 'Save'}
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
    <div className="space-y-1">
      <div className="text-[12px] font-medium text-claude-text flex items-baseline gap-2">
        {label}
        {hint && (
          <span className="text-claude-textFaint font-normal">{hint}</span>
        )}
      </div>
      {children}
    </div>
  )
}
