import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from '../i18n'

interface Props {
  content: string
  onApprove: () => void
  onReject: () => void
}

export function PlanApprovalModal({ content, onApprove, onReject }: Props) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-[2px] p-4">
      <div className="w-full max-w-2xl bg-claude-cream dark:bg-claude-panel rounded-2xl shadow-modal flex flex-col max-h-[85vh] overflow-hidden">
        <div className="px-5 py-3 border-b border-claude-border/60 text-[15px] font-medium">
          {t('plan.approveTitle')}
        </div>
        <div className="flex-1 overflow-y-auto p-5 prose-msg text-[14px]">
          {content ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          ) : (
            <div className="text-claude-textFaint italic">
              {t('plan.empty')}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-claude-border/60">
          <button
            onClick={onReject}
            className="px-3 py-1.5 text-[13px] text-claude-textDim hover:text-claude-text transition-colors"
          >
            {t('plan.reject')}
          </button>
          <button
            onClick={onApprove}
            className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover text-white rounded-md text-[13px] font-medium transition-colors"
          >
            {t('plan.approve')}
          </button>
        </div>
      </div>
    </div>
  )
}
