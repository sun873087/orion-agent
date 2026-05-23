import { useEffect } from 'react'
import { Keyboard, X } from 'lucide-react'

import { useTranslation } from '../i18n'

/**
 * 鍵盤快捷鍵 cheat sheet — 全域按 `?` 觸發,App.tsx 用 useKeyboardShortcutsHotkey
 * 控 open state。分組顯示:輸入框 / 對話 / 全域。Esc / 點外面 / X 都關。
 *
 * 增/改快捷鍵的維護:i18n key shortcuts.* 加新 entry,然後在這檔 GROUPS 加一筆。
 * 鍵 visual 用 <kbd>;組合鍵用「+」連接,連按鍵用「× 2」標。
 */
export function KeyboardShortcutsModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()

  // Esc 關閉(modal 開時才掛,避免影響其他層)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const groups: Array<{
    titleKey: string
    items: Array<{ keys: string[]; labelKey: string; descKey?: string }>
  }> = [
    {
      titleKey: 'shortcuts.group.input',
      items: [
        { keys: ['Enter'], labelKey: 'shortcuts.input.send' },
        { keys: ['Shift', 'Enter'], labelKey: 'shortcuts.input.newline' },
        { keys: ['Tab'], labelKey: 'shortcuts.input.acceptSuggestion' },
        { keys: ['Esc', 'Esc'], labelKey: 'shortcuts.input.clear' },
        { keys: ['/'], labelKey: 'shortcuts.input.slash' },
        { keys: ['@'], labelKey: 'shortcuts.input.mention' },
      ],
    },
    {
      titleKey: 'shortcuts.group.modal',
      items: [
        { keys: ['Esc'], labelKey: 'shortcuts.modal.close' },
        { keys: ['Enter'], labelKey: 'shortcuts.modal.confirm' },
      ],
    },
    {
      titleKey: 'shortcuts.group.global',
      items: [
        { keys: ['?'], labelKey: 'shortcuts.global.cheatsheet' },
      ],
    },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-xl flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="flex items-center gap-2 text-base font-semibold text-fg-base">
            <Keyboard size={16} />
            {t('shortcuts.title')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            aria-label={t('shortcuts.close')}
          >
            <X size={16} />
          </button>
        </div>
        <div className="scrollbar-thin max-h-[60vh] overflow-y-auto px-5 py-4">
          {groups.map((g) => (
            <section key={g.titleKey} className="mb-5 last:mb-0">
              <h3 className="mb-2 text-[11px] uppercase tracking-wide text-fg-subtle">
                {t(g.titleKey)}
              </h3>
              <ul className="space-y-1.5">
                {g.items.map((it, i) => (
                  <li
                    key={`${g.titleKey}-${i}`}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span className="text-fg-base">{t(it.labelKey)}</span>
                    <span className="flex items-center gap-1">
                      {it.keys.map((k, kIdx) => (
                        <span key={kIdx} className="flex items-center gap-1">
                          <kbd className="rounded border border-bg-hover bg-bg-panel px-1.5 py-0.5 font-mono text-[10px] text-fg-base shadow-sm">
                            {k}
                          </kbd>
                          {kIdx < it.keys.length - 1 && (
                            <span className="text-[10px] text-fg-subtle">
                              {it.keys[kIdx] === it.keys[kIdx + 1] ? '×' : '+'}
                            </span>
                          )}
                        </span>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <div className="border-t border-bg-hover px-5 py-2.5 text-[10px] text-fg-subtle">
          {t('shortcuts.hint')}
        </div>
      </div>
    </div>
  )
}
