import type { PermissionAskEvent } from '../types/events'

interface Props {
  event: PermissionAskEvent
  onDecide: (
    decision: 'allow' | 'always_allow' | 'deny' | 'always_deny',
  ) => void
}

export function PermissionDialog({ event, onDecide }: Props) {
  return (
    <div className="bg-yellow-50 border-2 border-yellow-400 p-4 rounded-lg shadow-sm">
      <h3 className="font-semibold mb-2 text-yellow-900">
        🔐 Allow <code className="font-mono">{event.tool_name}</code>?
      </h3>
      <pre className="text-xs bg-white border border-yellow-200 p-2 rounded mb-3 overflow-x-auto whitespace-pre-wrap break-all max-h-40">
        {JSON.stringify(event.input, null, 2)}
      </pre>
      <div className="flex flex-wrap gap-2">
        <button
          className="px-3 py-1 bg-green-500 text-white rounded hover:bg-green-600 text-sm"
          onClick={() => onDecide('allow')}
        >
          Allow once
        </button>
        <button
          className="px-3 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 text-sm"
          onClick={() => onDecide('always_allow')}
        >
          Always allow
        </button>
        <button
          className="px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600 text-sm"
          onClick={() => onDecide('deny')}
        >
          Deny once
        </button>
        <button
          className="px-3 py-1 bg-red-700 text-white rounded hover:bg-red-800 text-sm"
          onClick={() => onDecide('always_deny')}
        >
          Always deny
        </button>
      </div>
      {event.timeout_seconds && (
        <div className="text-xs text-gray-500 mt-2">
          Timeout: {event.timeout_seconds}s
        </div>
      )}
    </div>
  )
}
