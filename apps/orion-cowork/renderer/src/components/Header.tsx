import { Settings as SettingsIcon, Sparkles } from 'lucide-react'

import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

type Props = {
  onOpenSettings: () => void
}

export function Header({ onOpenSettings }: Props) {
  const sessionId = useAgentStore((s) => s.sessionId)
  const initError = useAgentStore((s) => s.initError)
  const provider = useSettingsStore((s) => s.selectedProvider)
  const model = useSettingsStore((s) => s.selectedModel)

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-bg-hover bg-bg-panel px-6">
      <div className="flex items-center gap-2">
        <Sparkles size={16} className="text-accent" />
        <h1 className="text-sm font-semibold">Orion Cowork</h1>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onOpenSettings}
          className="flex items-center gap-2 rounded-md border border-bg-hover bg-bg-input px-2 py-1 font-mono text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          title="Settings"
        >
          <span>{provider}</span>
          <span className="text-fg-subtle">/</span>
          <span>{model}</span>
        </button>

        <span className="font-mono text-xs text-fg-subtle">
          {initError ? (
            <span className="text-error">{initError}</span>
          ) : sessionId ? (
            <span title={sessionId}>session: {sessionId.slice(0, 8)}</span>
          ) : (
            <span>initializing…</span>
          )}
        </span>

        <button
          type="button"
          onClick={onOpenSettings}
          className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          title="Settings"
        >
          <SettingsIcon size={16} />
        </button>
      </div>
    </header>
  )
}
