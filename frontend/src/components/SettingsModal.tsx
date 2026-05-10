import { useEffect, useState } from 'react'
import { ConnectionsPanel } from './ConnectionsPanel'
import { CustomInstructionsPanel } from './CustomInstructionsPanel'
import { MemoryPanel } from './MemoryPanel'
import { SettingsPanel } from './SettingsPanel'

type Tab = 'instructions' | 'settings' | 'memory' | 'connections'

interface Props {
  sessionId: string | null
  onClose: () => void
}

const TABS: { key: Tab; label: string; icon: JSX.Element }[] = [
  {
    key: 'instructions',
    label: 'Instructions',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path
          d="M3 4h10M3 8h10M3 12h6"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'settings',
    label: 'Settings',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'memory',
    label: 'Memory',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path
          d="M3 4a1 1 0 011-1h8a1 1 0 011 1v8a1 1 0 01-1 1H4a1 1 0 01-1-1V4z"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path
          d="M5.5 6.5h5M5.5 9h3"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'connections',
    label: 'Connections',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="4" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="12" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 8h4" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
  },
]

export function SettingsModal({ sessionId, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('instructions')

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-[2px] animate-fade-in p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl h-[600px] max-h-[85vh] bg-claude-cream rounded-2xl shadow-modal flex overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-52 shrink-0 bg-claude-panel/70 border-r border-claude-border/60 flex flex-col">
          <div className="px-4 pt-5 pb-3 text-[15px] font-semibold">
            Settings
          </div>
          <nav className="flex-1 px-2 space-y-0.5">
            {TABS.map((t) => (
              <button
                key={t.key}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] text-left transition-colors ${
                  tab === t.key
                    ? 'bg-claude-borderSoft text-claude-text font-medium'
                    : 'text-claude-textDim hover:bg-claude-borderSoft/60 hover:text-claude-text'
                }`}
                onClick={() => setTab(t.key)}
              >
                <span className="text-claude-textDim">{t.icon}</span>
                {t.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-center justify-between px-5 py-3 border-b border-claude-border/60">
            <div className="text-[15px] font-medium">
              {TABS.find((t) => t.key === tab)?.label}
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
          <div className="flex-1 overflow-y-auto">
            {tab === 'instructions' && (
              <CustomInstructionsPanel sessionId={sessionId} />
            )}
            {tab === 'settings' && <SettingsPanel />}
            {tab === 'memory' && <MemoryPanel />}
            {tab === 'connections' && <ConnectionsPanel />}
          </div>
        </div>
      </div>
    </div>
  )
}
