interface Props {
  toolName: string
  content: string
  isError?: boolean
}

const TRUNCATE_LIMIT = 600

export function ToolResultCard({ toolName, content, isError }: Props) {
  const truncated = content.length > TRUNCATE_LIMIT
  const display = truncated ? content.slice(0, TRUNCATE_LIMIT) + '\n...' : content
  const cls = isError
    ? 'bg-red-50 border-red-400'
    : 'bg-green-50 border-green-400'
  return (
    <div className={`${cls} border-l-4 px-3 py-2 rounded text-sm`}>
      <div className="font-semibold text-xs text-gray-600">
        {isError ? '❌' : '↳'} {toolName}
      </div>
      <pre className="mt-1 text-xs text-gray-800 overflow-x-auto whitespace-pre-wrap max-h-60">
        {display}
      </pre>
      {truncated && (
        <div className="text-xs text-gray-500 mt-1">
          ({content.length - TRUNCATE_LIMIT} more characters)
        </div>
      )}
    </div>
  )
}
