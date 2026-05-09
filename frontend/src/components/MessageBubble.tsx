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
        <div className="max-w-2xl bg-blue-600 text-white rounded-lg px-4 py-2 whitespace-pre-wrap">
          {text}
        </div>
      </div>
    )
  }
  if (role === 'thinking') {
    return (
      <div className="text-gray-500 text-sm italic px-4 py-1 whitespace-pre-wrap">
        💭 {text}
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-3xl bg-white border border-gray-200 rounded-lg px-4 py-2 prose-msg">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    </div>
  )
}
