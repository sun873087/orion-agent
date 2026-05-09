import { useState } from 'react'
import { CustomInstructionsPanel } from './CustomInstructionsPanel'
import { SettingsPanel } from './SettingsPanel'

type Tab = 'instructions' | 'settings' | 'memory' | 'connections'

interface Props {
  sessionId: string | null
}

export function RightSidebar({ sessionId }: Props) {
  const [tab, setTab] = useState<Tab>('instructions')

  return (
    <aside className="w-80 bg-white border-l border-gray-200 flex flex-col">
      <div className="border-b border-gray-200 flex">
        {(
          [
            ['instructions', 'Instructions'],
            ['settings', 'Settings'],
            ['memory', 'Memory'],
            ['connections', 'MCP'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            className={`flex-1 text-xs py-2 ${
              tab === key
                ? 'border-b-2 border-blue-600 text-blue-700 font-semibold'
                : 'text-gray-600 hover:bg-gray-50'
            }`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === 'instructions' && (
          <CustomInstructionsPanel sessionId={sessionId} />
        )}
        {tab === 'settings' && <SettingsPanel />}
        {tab === 'memory' && <PlaceholderPanel feature="Memory list" />}
        {tab === 'connections' && (
          <PlaceholderPanel feature="MCP OAuth connections" />
        )}
      </div>
    </aside>
  )
}

function PlaceholderPanel({ feature }: { feature: string }) {
  return (
    <div className="p-4 text-sm text-gray-500 space-y-2">
      <div className="font-semibold text-gray-700">{feature}</div>
      <p>
        This panel is reserved for a future backend phase. The corresponding
        REST endpoint is not yet implemented.
      </p>
      <p className="text-xs text-gray-400">
        See <code>docs/phases/</code> in the project root for upcoming phases.
      </p>
    </div>
  )
}
