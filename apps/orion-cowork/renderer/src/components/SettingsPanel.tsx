import { useEffect } from 'react'
import { X, Check, AlertCircle, Sun, Moon } from 'lucide-react'

import { fetchModels } from '../api/agent'
import { useSettingsStore } from '../store/settings'

type Props = {
  open: boolean
  onClose: () => void
}

/** Modal — model picker / theme / API key 狀態。 */
export function SettingsPanel({ open, onClose }: Props) {
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
          <h2 className="text-sm font-semibold">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            <X size={16} />
          </button>
        </header>

        <div className="scrollbar-thin flex-1 overflow-y-auto px-5 py-4">
          {/* Theme */}
          <Section title="Appearance">
            <button
              type="button"
              onClick={toggleTheme}
              className="flex items-center gap-3 rounded-lg border border-bg-hover bg-bg-panel px-4 py-2 text-sm hover:bg-bg-hover"
            >
              {theme === 'dark' ? <Moon size={14} /> : <Sun size={14} />}
              <span>
                {theme === 'dark' ? 'Dark' : 'Light'} mode
              </span>
              <span className="text-xs text-fg-subtle">— click to toggle</span>
            </button>
          </Section>

          {/* Model picker */}
          <Section title="Model">
            {!catalogLoaded ? (
              <div className="text-sm text-fg-muted">loading catalog…</div>
            ) : providers.length === 0 ? (
              <div className="text-sm text-error">
                Failed to load catalog. Check sidecar is running.
              </div>
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

          {/* About */}
          <Section title="About">
            <div className="text-xs text-fg-subtle">
              Orion Cowork · Phase 31-C. Model + theme persist to localStorage.
            </div>
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
  return (
    <div className="rounded-lg border border-bg-hover bg-bg-panel">
      <div className="flex items-center justify-between border-b border-bg-hover px-3 py-2">
        <span className="text-sm font-medium">{provider.label}</span>
        {provider.api_key_configured ? (
          <span className="flex items-center gap-1 text-xs text-success">
            <Check size={12} /> API key set
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-warning">
            <AlertCircle size={12} /> no API key — set in .env
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
                    reasoning
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
