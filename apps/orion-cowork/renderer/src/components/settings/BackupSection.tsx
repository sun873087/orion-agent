import { useEffect, useState } from 'react'
import { Archive, Download, RefreshCw, Upload } from 'lucide-react'

import {
  type BackupManifest,
  type BackupPreview,
  backupExport,
  backupInspect,
  backupPreview,
  backupRestore,
} from '../../api/agent'
import { useTranslation } from '../../i18n'

/** Bytes → human readable(KB / MB / GB)。 */
function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function epochToLocale(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString()
}

export function BackupSection() {
  const { t } = useTranslation()
  const [includeBlobs, setIncludeBlobs] = useState(true)
  const [preview, setPreview] = useState<BackupPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState<{ path: string; bytes: number } | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  // Restore state
  const [restoreManifest, setRestoreManifest] = useState<{
    manifest: BackupManifest
    zip_size: number
    source_path: string
  } | null>(null)
  const [restoring, setRestoring] = useState(false)
  const [restoreDone, setRestoreDone] = useState<{ moved_to: string } | null>(null)
  const [restoreError, setRestoreError] = useState<string | null>(null)

  // 跟 includeBlobs toggle 即時 refresh preview
  useEffect(() => {
    let cancelled = false
    setPreviewError(null)
    backupPreview(includeBlobs)
      .then((p) => {
        if (!cancelled) setPreview(p)
      })
      .catch((e) => {
        if (!cancelled) setPreviewError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [includeBlobs])

  // 訂閱 restart_required notification(restore handler 推的)
  useEffect(() => {
    const unsub = window.backupApi.onRestartRequired((data) => {
      setRestoreDone({ moved_to: data.moved_to })
    })
    return unsub
  }, [])

  const handleExport = async () => {
    setExportError(null)
    setExportResult(null)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const defaultName = `orion-backup-${ts}.zip`
    const target = await window.backupApi.pickSavePath(defaultName)
    if (!target) return
    setExporting(true)
    try {
      const r = await backupExport(target, includeBlobs)
      setExportResult({ path: r.path, bytes: r.total_bytes })
    } catch (e) {
      setExportError(String(e))
    } finally {
      setExporting(false)
    }
  }

  const handlePickRestore = async () => {
    setRestoreError(null)
    setRestoreDone(null)
    const src = await window.backupApi.pickOpenPath()
    if (!src) return
    try {
      const info = await backupInspect(src)
      setRestoreManifest({ ...info, source_path: src })
    } catch (e) {
      setRestoreError(String(e))
    }
  }

  const handleConfirmRestore = async () => {
    if (!restoreManifest) return
    setRestoring(true)
    setRestoreError(null)
    try {
      await backupRestore(restoreManifest.source_path)
      // restart_required notification 會 set restoreDone(useEffect 監聽)
    } catch (e) {
      setRestoreError(String(e))
    } finally {
      setRestoring(false)
      setRestoreManifest(null)
    }
  }

  return (
    <div className="space-y-8">
      {/* Export */}
      <section>
        <h3 className="mb-2 flex items-center gap-2 text-base font-medium">
          <Download size={16} />
          {t('settings.backup.exportTitle')}
        </h3>
        <p className="mb-4 text-sm text-fg-muted">{t('settings.backup.exportDesc')}</p>

        <label className="mb-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeBlobs}
            onChange={(e) => setIncludeBlobs(e.target.checked)}
            disabled={exporting}
          />
          {t('settings.backup.includeBlobs')}
        </label>

        {preview && (
          <div className="mb-4 rounded border border-bg-hover bg-bg-sub p-3 text-xs text-fg-muted">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <div>{t('settings.backup.sizeDb')}</div>
              <div className="text-right text-fg-base">{humanSize(preview.db_bytes)}</div>
              <div>{t('settings.backup.sizeOther')}</div>
              <div className="text-right text-fg-base">{humanSize(preview.other_bytes)}</div>
              <div>
                {t('settings.backup.sizeBlobs')} ({preview.blobs_count})
              </div>
              <div className="text-right text-fg-base">
                {humanSize(preview.blobs_bytes)}
                {!includeBlobs && (
                  <span className="ml-1 text-fg-muted">
                    ({t('settings.backup.excluded')})
                  </span>
                )}
              </div>
              <div className="border-t border-bg-hover pt-1 font-medium">
                {t('settings.backup.sizeTotal')}
              </div>
              <div className="border-t border-bg-hover pt-1 text-right font-medium text-fg-base">
                {humanSize(preview.total_bytes)}
              </div>
            </div>
          </div>
        )}
        {previewError && (
          <div className="mb-3 rounded bg-red-500/10 p-2 text-xs text-red-500">
            {previewError}
          </div>
        )}

        <button
          type="button"
          onClick={handleExport}
          disabled={exporting}
          className="rounded bg-fg-base px-3 py-1.5 text-sm text-bg-base hover:bg-fg-base/90 disabled:opacity-50"
        >
          {exporting ? t('settings.backup.exporting') : t('settings.backup.exportButton')}
        </button>

        {exportResult && (
          <div className="mt-3 rounded bg-green-500/10 p-2 text-xs text-green-700 dark:text-green-400">
            ✓ {t('settings.backup.exportDone', {
              size: humanSize(exportResult.bytes),
              path: exportResult.path,
            })}
          </div>
        )}
        {exportError && (
          <div className="mt-3 rounded bg-red-500/10 p-2 text-xs text-red-500">{exportError}</div>
        )}
      </section>

      {/* Restore */}
      <section>
        <h3 className="mb-2 flex items-center gap-2 text-base font-medium">
          <Upload size={16} />
          {t('settings.backup.restoreTitle')}
        </h3>
        <p className="mb-4 text-sm text-fg-muted">{t('settings.backup.restoreDesc')}</p>

        {!restoreManifest && !restoreDone && (
          <button
            type="button"
            onClick={handlePickRestore}
            className="rounded border border-bg-hover px-3 py-1.5 text-sm hover:bg-bg-hover"
          >
            <Archive className="mr-1 inline" size={14} />
            {t('settings.backup.pickBackup')}
          </button>
        )}

        {restoreManifest && !restoreDone && (
          <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
            <div className="mb-2 font-medium">
              {t('settings.backup.restoreConfirmTitle')}
            </div>
            <ul className="mb-3 space-y-1 text-xs text-fg-muted">
              <li>
                {t('settings.backup.manifestExportedAt')}:{' '}
                {epochToLocale(restoreManifest.manifest.exported_at)}
              </li>
              <li>
                {t('settings.backup.manifestSource')}: {restoreManifest.manifest.data_dir}
              </li>
              <li>
                {t('settings.backup.manifestSize')}: {humanSize(restoreManifest.zip_size)} (
                {restoreManifest.manifest.file_count} files)
              </li>
              <li>
                {t('settings.backup.manifestIncludesBlobs')}:{' '}
                {restoreManifest.manifest.include_blobs ? '✓' : '✗'}
              </li>
            </ul>
            <p className="mb-3 text-xs text-amber-700 dark:text-amber-400">
              ⚠️ {t('settings.backup.restoreWarning')}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleConfirmRestore}
                disabled={restoring}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700 disabled:opacity-50"
              >
                {restoring ? t('settings.backup.restoring') : t('settings.backup.confirmRestore')}
              </button>
              <button
                type="button"
                onClick={() => setRestoreManifest(null)}
                disabled={restoring}
                className="rounded px-3 py-1.5 text-sm hover:bg-bg-hover"
              >
                {t('settings.backup.cancel')}
              </button>
            </div>
          </div>
        )}

        {restoreDone && (
          <div className="rounded border border-green-500/40 bg-green-500/10 p-3 text-sm">
            <div className="mb-2 font-medium text-green-700 dark:text-green-400">
              ✓ {t('settings.backup.restoreDone')}
            </div>
            <p className="mb-3 text-xs text-fg-muted">
              {t('settings.backup.movedTo')}: <code>{restoreDone.moved_to}</code>
            </p>
            <p className="mb-3 text-xs text-fg-muted">{t('settings.backup.restartNeeded')}</p>
            <button
              type="button"
              onClick={() => window.backupApi.relaunch()}
              className="rounded bg-fg-base px-3 py-1.5 text-sm text-bg-base hover:bg-fg-base/90"
            >
              <RefreshCw className="mr-1 inline" size={14} />
              {t('settings.backup.restartNow')}
            </button>
          </div>
        )}

        {restoreError && (
          <div className="mt-3 rounded bg-red-500/10 p-2 text-xs text-red-500">{restoreError}</div>
        )}
      </section>
    </div>
  )
}
