import { useEffect, useState } from 'react'
import { Folder, X } from 'lucide-react'

import { getPrefs, setPref } from '../../api/agent'
import { useTranslation } from '../../i18n'

export function GeneralSection() {
  const { t } = useTranslation()
  const [defaultWorkspace, setDefaultWorkspace] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      const p = await getPrefs()
      setDefaultWorkspace(p.default_workspace_dir || null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function pick() {
    const dir = await window.dialog.selectFolder()
    if (!dir) return
    await setPref('default_workspace_dir', dir)
    setDefaultWorkspace(dir)
  }

  async function clear() {
    await setPref('default_workspace_dir', null)
    setDefaultWorkspace(null)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-fg-muted">
          {t('general.defaultWorkspace')}
        </label>
        <p className="text-[11px] text-fg-subtle">
          {t('general.defaultWorkspaceHint')}
        </p>
        {loading && !defaultWorkspace ? (
          <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
        ) : defaultWorkspace ? (
          <div className="mt-2 flex w-fit items-center gap-2 rounded-md border border-bg-hover bg-bg-panel px-3 py-1.5">
            <Folder size={14} className="text-fg-muted" />
            <span className="font-mono text-xs text-fg-base">{defaultWorkspace}</span>
            <button
              type="button"
              onClick={pick}
              className="rounded px-2 py-0.5 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            >
              {t('general.change')}
            </button>
            <button
              type="button"
              onClick={clear}
              className="rounded p-1 text-fg-subtle hover:bg-error/20 hover:text-error"
              title={t('general.clear')}
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={pick}
            className="mt-2 flex w-fit items-center gap-2 rounded-md border border-bg-hover bg-bg-panel px-4 py-1.5 text-sm hover:bg-bg-hover"
          >
            <Folder size={14} />
            <span>{t('general.pickFolder')}</span>
          </button>
        )}
      </div>
    </div>
  )
}
