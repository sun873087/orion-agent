import { useEffect, useRef, useState } from 'react'
import type { ModelCatalog } from '../types/events'
import type { ModelChoice } from '../lib/preferredModel'

interface Props {
  value: ModelChoice
  onChange: (choice: ModelChoice) => void
  catalog: ModelCatalog | null
  loading?: boolean
  disabled?: boolean
  /** 'up' 讓選單往上展開 — 用在貼底的輸入框內,避免被視窗底裁掉。 */
  direction?: 'up' | 'down'
}

export function ModelPicker({
  value,
  onChange,
  catalog,
  loading,
  disabled,
  direction = 'down',
}: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const currentLabel = catalog
    ? (findLabel(catalog, value) ?? value.model)
    : value.model

  function pick(choice: ModelChoice) {
    setOpen(false)
    if (choice.provider === value.provider && choice.model === value.model)
      return
    onChange(choice)
  }

  return (
    <div ref={ref} className="relative inline-block text-[13px]">
      <button
        type="button"
        title="Select model"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white dark:bg-claude-panel border border-claude-border hover:border-claude-orange/50 hover:bg-claude-cream/50 dark:hover:bg-claude-panel/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled || loading}
      >
        <span className="font-medium text-claude-text">
          {loading ? 'Loading…' : currentLabel}
        </span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="none"
          className={`text-claude-textDim transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <path
            d="M4 6l4 4 4-4"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open && catalog && (
        <div
          className={`absolute right-0 w-72 z-30 bg-white dark:bg-claude-panel dark:ring-1 dark:ring-claude-border rounded-xl shadow-modal dark:shadow-[0_25px_50px_-12px_rgba(0,0,0,0.6)] py-1.5 animate-fade-in max-h-96 overflow-y-auto ${
            direction === 'up' ? 'bottom-full mb-1.5' : 'top-full mt-1.5'
          }`}
        >
          {catalog.providers.map((p) => (
            <div key={p.id} className="py-1">
              <div className="px-3 py-1 flex items-center gap-2 text-[11px] uppercase tracking-wider text-claude-textFaint">
                {p.label}
                {!p.available && (
                  <span
                    className="text-claude-textFaint normal-case tracking-normal italic"
                    title={`API key for ${p.label} not configured`}
                  >
                    · key not configured
                  </span>
                )}
              </div>
              {p.models.map((m) => {
                const selected = p.id === value.provider && m.id === value.model
                const disabledRow = !p.available
                return (
                  <button
                    key={`${p.id}:${m.id}`}
                    type="button"
                    className={`w-full text-left px-3 py-2 flex items-center gap-2 ${
                      disabledRow
                        ? 'text-claude-textFaint cursor-not-allowed'
                        : selected
                          ? 'bg-claude-orangeSoft/40 text-claude-text'
                          : 'text-claude-text hover:bg-claude-borderSoft/60'
                    }`}
                    onClick={() => {
                      if (disabledRow) return
                      pick({ provider: p.id, model: m.id })
                    }}
                    disabled={disabledRow}
                    title={
                      disabledRow ? `${p.label} key not configured` : undefined
                    }
                  >
                    <span className="flex-1">{m.label}</span>
                    {selected && (
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 16 16"
                        fill="none"
                        className="text-claude-orange"
                      >
                        <path
                          d="M3 8l3.5 3.5L13 5"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function findLabel(catalog: ModelCatalog, choice: ModelChoice): string | null {
  const p = catalog.providers.find((p) => p.id === choice.provider)
  if (!p) return null
  const m = p.models.find((m) => m.id === choice.model)
  return m?.label ?? null
}
