import { useEffect, useState } from 'react'
import { X, Check, AlertCircle, Sun, Moon, RotateCw, Plug, PlugZap } from 'lucide-react'

import { fetchMcpStatus, fetchModels, reconnectMcp, type McpStatus } from '../api/agent'
import { useTranslation } from '../i18n'
import { useSettingsStore } from '../store/settings'

/** Modal — model picker / theme / language / API key 狀態。 */
export function SettingsPanel() {
  const { t } = useTranslation()
  const open = useSettingsStore((s) => s.settingsOpen)
  const onClose = useSettingsStore((s) => s.closeSettings)
  const providers = useSettingsStore((s) => s.providers)
  const catalogLoaded = useSettingsStore((s) => s.catalogLoaded)
  const setCatalog = useSettingsStore((s) => s.setCatalog)
  const selectedProvider = useSettingsStore((s) => s.selectedProvider)
  const selectedModel = useSettingsStore((s) => s.selectedModel)
  const setSelectedModel = useSettingsStore((s) => s.setSelectedModel)
  const theme = useSettingsStore((s) => s.theme)
  const toggleTheme = useSettingsStore((s) => s.toggleTheme)

  useEffect(() => {
    if (!open || catalogLoaded) return
    fetchModels()
      .then((cat) =>
        setCatalog(
          cat.providers.map((p) => ({
            id: p.id,
            label: p.label,
            models: p.models,
            api_key_configured: p.api_key_configured,
          })),
        ),
      )
      .catch(() => {
        /* failed — leave empty,UI 顯示提示 */
      })
  }, [open, catalogLoaded, setCatalog])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="text-sm font-semibold">{t('settings.title')}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            title={t('settings.close')}
          >
            <X size={16} />
          </button>
        </header>

        <div className="scrollbar-thin flex-1 overflow-y-auto px-5 py-4">
          {/* Appearance */}
          <Section title={t('settings.section.appearance')}>
            <button
              type="button"
              onClick={toggleTheme}
              className="flex items-center gap-3 rounded-lg border border-bg-hover bg-bg-panel px-4 py-2 text-sm hover:bg-bg-hover"
            >
              {theme === 'dark' ? <Moon size={14} /> : <Sun size={14} />}
              <span>
                {theme === 'dark' ? t('settings.theme.dark') : t('settings.theme.light')}
              </span>
              <span className="text-xs text-fg-subtle">{t('settings.theme.toggleHint')}</span>
            </button>
          </Section>

          {/* Model picker */}
          <Section title={t('settings.section.model')}>
            {!catalogLoaded ? (
              <div className="text-sm text-fg-muted">{t('settings.model.loading')}</div>
            ) : providers.length === 0 ? (
              <div className="text-sm text-error">{t('settings.model.failed')}</div>
            ) : (
              <div className="flex flex-col gap-3">
                {providers.map((p) => (
                  <ProviderBlock
                    key={p.id}
                    provider={p}
                    selectedProvider={selectedProvider}
                    selectedModel={selectedModel}
                    onSelect={(mid) => setSelectedModel(p.id, mid)}
                  />
                ))}
              </div>
            )}
          </Section>

          {/* MCP servers */}
          <Section title={t('settings.section.mcp')}>
            <McpSection open={open} />
          </Section>

          {/* About */}
          <Section title={t('settings.section.about')}>
            <div className="text-xs text-fg-subtle">{t('settings.about.text')}</div>
          </Section>
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-6 last:mb-0">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        {title}
      </h3>
      {children}
    </section>
  )
}

function ProviderBlock({
  provider,
  selectedProvider,
  selectedModel,
  onSelect,
}: {
  provider: {
    id: string
    label: string
    models: Array<{ id: string; label: string; supports_reasoning?: boolean }>
    api_key_configured: boolean
  }
  selectedProvider: string
  selectedModel: string
  onSelect: (modelId: string) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="rounded-lg border border-bg-hover bg-bg-panel">
      <div className="flex items-center justify-between border-b border-bg-hover px-3 py-2">
        <span className="text-sm font-medium">{provider.label}</span>
        {provider.api_key_configured ? (
          <span className="flex items-center gap-1 text-xs text-success">
            <Check size={12} /> {t('settings.model.apiKeySet')}
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-warning">
            <AlertCircle size={12} /> {t('settings.model.apiKeyMissing')}
          </span>
        )}
      </div>
      <div className="flex flex-col">
        {provider.models.map((m) => {
          const active =
            selectedProvider === provider.id && selectedModel === m.id
          return (
            <button
              key={m.id}
              type="button"
              disabled={!provider.api_key_configured}
              onClick={() => onSelect(m.id)}
              className={`flex items-center justify-between px-3 py-2 text-left text-sm transition-colors ${
                active
                  ? 'bg-accent/15 text-accent'
                  : 'text-fg-base hover:bg-bg-hover'
              } disabled:cursor-not-allowed disabled:opacity-40`}
            >
              <span className="flex items-center gap-2">
                {active && <Check size={12} />}
                <span>{m.label}</span>
                {m.supports_reasoning && (
                  <span className="rounded bg-bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                    {t('settings.model.reasoning')}
                  </span>
                )}
              </span>
              <span className="font-mono text-[10px] text-fg-subtle">{m.id}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function McpSection({ open }: { open: boolean }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<McpStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [reconnecting, setReconnecting] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      const s = await fetchMcpStatus()
      setStatus(s)
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) refresh()
  }, [open])

  async function handleReconnect(name: string) {
    setReconnecting(name)
    try {
      await reconnectMcp(name)
      await refresh()
    } finally {
      setReconnecting(null)
    }
  }

  if (loading && !status) {
    return <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
  }
  if (!status) {
    return <div className="text-sm text-error">{t('settings.mcp.failed')}</div>
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-fg-subtle">
        {t('settings.mcp.config')} <code className="font-mono">{status.config_path}</code>
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
      {status.servers.length === 0 ? (
        <div className="whitespace-pre-line rounded-lg border border-dashed border-bg-hover p-3 text-center text-xs text-fg-subtle">
          {t('settings.mcp.none')}
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {status.servers.map((s) => (
            <li
              key={s.name}
              className="flex items-center justify-between gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2"
            >
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <StatusIcon status={s.status} />
                <div className="min-w-0 flex-1">
                  <div className="font-mono text-sm text-fg-base">{s.name}</div>
                  {s.status === 'connected' && (
                    <div className="text-xs text-fg-subtle">
                      {t('settings.mcp.tools', { n: s.tools.length })}
                    </div>
                  )}
                  {s.error && (
                    <div className="truncate text-xs text-error" title={s.error}>
                      {s.error}
                    </div>
                  )}
                </div>
              </div>
              {s.status !== 'connected' && (
                <button
                  type="button"
                  onClick={() => handleReconnect(s.name)}
                  disabled={reconnecting === s.name}
                  className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:opacity-40"
                  title={t('settings.mcp.reconnect')}
                >
                  <RotateCw
                    size={14}
                    className={reconnecting === s.name ? 'animate-spin' : ''}
                  />
                </button>
              )}
            </li>
          ))}
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
