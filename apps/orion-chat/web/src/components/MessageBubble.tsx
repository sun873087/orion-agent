import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props {
  role: 'user' | 'assistant' | 'thinking'
  text: string
}

export function MessageBubble({ role, text }: Props) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] bg-claude-panel text-claude-text rounded-2xl px-4 py-2.5 whitespace-pre-wrap text-[15px] leading-relaxed">
          {text}
        </div>
      </div>
    )
  }
  if (role === 'thinking') {
    return (
      <div className="flex items-start gap-2 text-claude-textDim text-[14px] italic px-1 py-1 whitespace-pre-wrap">
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          className="mt-1 shrink-0 opacity-60"
        >
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M8 5v3l2 1.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
        <div>{text}</div>
      </div>
    )
  }
  return (
    <div className="prose-msg">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
}
