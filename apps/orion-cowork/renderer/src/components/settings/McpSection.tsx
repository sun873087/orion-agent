import { useEffect, useState } from 'react'
import { AlertCircle, Pencil, Plug, PlugZap, Plus, RotateCw, Trash2 } from 'lucide-react'

import {
  deleteMcpConfig,
  fetchMcpStatus,
  listMcpConfigs,
  reconnectMcp,
  upsertMcpConfig,
  type McpConfigEntry,
  type McpServerConfig,
  type McpStatus,
} from '../../api/agent'
import { useTranslation } from '../../i18n'

type EditTarget = { mode: 'new' } | { mode: 'edit'; entry: McpConfigEntry } | null

export function McpSection({ projectId }: { projectId?: string | null } = {}) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<McpStatus | null>(null)
  const [configs, setConfigs] = useState<McpConfigEntry[]>([])
  const [configPath, setConfigPath] = useState('')
  const [loading, setLoading] = useState(false)
  const [reconnecting, setReconnecting] = useState<string | null>(null)
  const [edit, setEdit] = useState<EditTarget>(null)

  async function refresh() {
    setLoading(true)
    try {
      // Project scope:只 read project's mcp.json,不查 connection status
      // (那是 global 的)
      const cfg = await listMcpConfigs(projectId ?? null)
      if (!projectId) {
        const st = await fetchMcpStatus()
        setStatus(st)
      } else {
        setStatus({ config_path: cfg.config_path, servers: [] })
      }
      setConfigs(cfg.servers)
      setConfigPath(cfg.config_path)
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [projectId])

  async function handleReconnect(name: string) {
    setReconnecting(name)
    try {
      await reconnectMcp(name)
      await refresh()
    } finally {
      setReconnecting(null)
    }
  }

  async function handleDelete(name: string) {
    if (!window.confirm(t('mcp.deleteConfirm', { name }))) return
    await deleteMcpConfig(name, projectId ?? null)
    await refresh()
  }

  if (edit) {
    return (
      <McpEditor
        target={edit}
        projectId={projectId ?? null}
        onClose={() => setEdit(null)}
        onSaved={async () => {
          setEdit(null)
          await refresh()
        }}
      />
    )
  }

  // Merge status + configs:UI 列依 configs(可能 status 還沒拿到 / pending)
  const statusByName = new Map(
    (status?.servers ?? []).map((s) => [s.name, s] as const),
  )

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-fg-subtle">
          {t('settings.mcp.config')}{' '}
          <code className="font-mono text-fg-muted">{configPath}</code>
          <button
            type="button"
            onClick={refresh}
            className="ml-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            title={t('settings.mcp.refreshTitle')}
          >
            <RotateCw size={11} />
            <span>{t('settings.mcp.refresh')}</span>
          </button>
        </div>
        <button
          type="button"
          onClick={() => setEdit({ mode: 'new' })}
          className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
        >
          <Plus size={12} />
          <span>{t('mcp.new')}</span>
        </button>
      </div>

      {loading && configs.length === 0 ? (
        <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
      ) : configs.length === 0 ? (
        <div className="whitespace-pre-line rounded-lg border border-dashed border-bg-hover p-6 text-center text-xs text-fg-subtle">
          {t('mcp.empty')}
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {configs.map((entry) => {
            const st = statusByName.get(entry.name)
            return (
              <li
                key={entry.name}
                className="flex items-center justify-between gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <StatusIcon status={st?.status ?? 'pending'} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm text-fg-base">{entry.name}</span>
                      <span className="rounded bg-bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                        {entry.config.type}
                      </span>
                    </div>
                    {st?.status === 'connected' && (
                      <div className="text-xs text-fg-subtle">
                        {t('settings.mcp.tools', { n: st.tools.length })}
                      </div>
                    )}
                    {st?.error && (
                      <div className="truncate text-xs text-error" title={st.error}>
                        {st.error}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {st && st.status !== 'connected' && (
                    <button
                      type="button"
                      onClick={() => handleReconnect(entry.name)}
                      disabled={reconnecting === entry.name}
                      className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:opacity-40"
                      title={t('settings.mcp.reconnect')}
                    >
                      <RotateCw
                        size={14}
                        className={reconnecting === entry.name ? 'animate-spin' : ''}
                      />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setEdit({ mode: 'edit', entry })}
                    className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
                    title={t('mcp.edit')}
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(entry.name)}
                    className="rounded p-1 text-fg-muted hover:bg-error/20 hover:text-error"
                    title={t('mcp.delete')}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function StatusIcon({ status }: { status: McpStatus['servers'][number]['status'] }) {
  if (status === 'connected') return <PlugZap size={14} className="text-success" />
  if (status === 'pending') return <Plug size={14} className="text-fg-muted" />
  return <AlertCircle size={14} className="text-warning" />
}

function McpEditor({
  target,
  projectId,
  onClose,
  onSaved,
}: {
  target: { mode: 'new' } | { mode: 'edit'; entry: McpConfigEntry }
  projectId?: string | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { t } = useTranslation()
  const existing = target.mode === 'edit' ? target.entry : null
  const [name, setName] = useState(existing?.name ?? '')
  const [type, setType] = useState<'stdio' | 'http'>(existing?.config.type ?? 'stdio')
  const [command, setCommand] = useState(
    existing && existing.config.type === 'stdio' ? existing.config.command : '',
  )
  const [argsText, setArgsText] = useState(
    existing && existing.config.type === 'stdio'
      ? (existing.config.args ?? []).join('\n')
      : '',
  )
  const [url, setUrl] = useState(
    existing && existing.config.type === 'http' ? existing.config.url : '',
  )
  const [envText, setEnvText] = useState(
    existing
      ? envOrHeadersToText(
          existing.config.type === 'stdio'
            ? existing.config.env
            : existing.config.headers,
        )
      : '',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid =
    name.trim() &&
    (type === 'stdio' ? command.trim() : url.trim())

  async function handleSave() {
    if (!valid || busy) return
    setBusy(true)
    setError(null)
    try {
      const envMap = parseKvPairs(envText)
      let cfg: McpServerConfig
      if (type === 'stdio') {
        const args = argsText
          .split('\n')
          .map((s) => s.trim())
          .filter((s) => s.length > 0)
        cfg = {
          type: 'stdio',
          command: command.trim(),
          args: args.length ? args : undefined,
          env: Object.keys(envMap).length ? envMap : undefined,
        }
      } else {
        cfg = {
          type: 'http',
          url: url.trim(),
          headers: Object.keys(envMap).length ? envMap : undefined,
        }
      }
      await upsertMcpConfig(
        name.trim(),
        cfg,
        existing && existing.name !== name.trim() ? existing.name : undefined,
        projectId ?? null,
      )
      await onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
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
        ← {t('memory.backToList')}
      </button>

      <div className="flex flex-col gap-3 rounded-lg border border-bg-hover bg-bg-panel p-4">
        <Field label={t('mcp.field.name')}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('mcp.field.namePlaceholder')}
            className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </Field>
        <Field label={t('mcp.field.type')}>
          <div className="flex gap-2">
            <TypeChip active={type === 'stdio'} onClick={() => setType('stdio')}>
              stdio
            </TypeChip>
            <TypeChip active={type === 'http'} onClick={() => setType('http')}>
              http
            </TypeChip>
          </div>
        </Field>

        {type === 'stdio' ? (
          <>
            <Field
              label={t('mcp.field.command')}
              hint={t('mcp.field.commandHint')}
            >
              <input
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="npx"
                className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </Field>
            <Field
              label={t('mcp.field.args')}
              hint={t('mcp.field.argsHint')}
            >
              <textarea
                value={argsText}
                onChange={(e) => setArgsText(e.target.value)}
                rows={3}
                placeholder={'-y\n@modelcontextprotocol/server-filesystem\n/Users/me/projects'}
                className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </Field>
            <Field
              label={t('mcp.field.env')}
              hint={t('mcp.field.envHint')}
            >
              <textarea
                value={envText}
                onChange={(e) => setEnvText(e.target.value)}
                rows={3}
                placeholder={'API_KEY=xxx\nLANG=en'}
                className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </Field>
          </>
        ) : (
          <>
            <Field label={t('mcp.field.url')}>
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://mcp.example.com/sse"
                className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </Field>
            <Field
              label={t('mcp.field.headers')}
              hint={t('mcp.field.envHint')}
            >
              <textarea
                value={envText}
                onChange={(e) => setEnvText(e.target.value)}
                rows={3}
                placeholder={'Authorization=Bearer xxx'}
                className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </Field>
          </>
        )}

        {error && (
          <div className="rounded-md bg-error/10 px-3 py-2 text-xs text-error">
            {error}
          </div>
        )}

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
            disabled={!valid || busy}
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

function TypeChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border px-3 py-1 font-mono text-xs transition-colors ${
        active
          ? 'border-accent bg-accent/15 text-accent'
          : 'border-bg-hover bg-bg-input text-fg-muted hover:bg-bg-hover'
      }`}
    >
      {children}
    </button>
  )
}

function envOrHeadersToText(m: Record<string, string> | undefined): string {
  if (!m) return ''
  return Object.entries(m)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n')
}

function parseKvPairs(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const idx = trimmed.indexOf('=')
    if (idx < 0) continue
    const k = trimmed.slice(0, idx).trim()
    const v = trimmed.slice(idx + 1)
    if (k) out[k] = v
  }
  return out
}
