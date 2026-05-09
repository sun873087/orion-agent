interface Props {
  toolName: string
  input: Record<string, unknown>
}

export function ToolUseCard({ toolName, input }: Props) {
  return (
    <div className="bg-blue-50 border-l-4 border-blue-400 px-3 py-2 rounded text-sm">
      <div className="font-semibold text-blue-900 flex items-center gap-2">
        🔧 <span>{toolName}</span>
      </div>
      <pre className="mt-1 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap break-all">
        {JSON.stringify(input, null, 2)}
      </pre>
    </div>
  )
}
