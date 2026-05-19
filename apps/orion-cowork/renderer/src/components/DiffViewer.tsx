/**
 * Inline unified diff viewer(Phase 31-V)— 顯 Edit / Write / NotebookEdit 改了什麼。
 *
 * 拿 before_blob_id / after_blob_id 透過 sidecar conversation.read_blob_text 拉
 * 兩個內容,用 `diff` lib 算 line-level diff,渲染紅 `-` / 綠 `+` /灰 context。
 *
 * 預設摺起,只顯一行 summary(+M −N · file path);user 點開展全 diff。
 */
import { useEffect, useMemo, useState } from 'react'
import { diffLines } from 'diff'
import { ChevronDown, ChevronRight, FileText } from 'lucide-react'

import { readBlobText } from '../api/agent'
import { useTranslation } from '../i18n'

type EditSnapshot = {
  filePath: string | null
  beforeBlobId: string | null
  afterBlobId: string | null
}

export function DiffViewer({ snapshot }: { snapshot: EditSnapshot }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const [before, setBefore] = useState<string | null>(null)
  const [after, setAfter] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // Lazy load:expand 第一次才拉,避免 history 一次撈幾百筆 blob
  useEffect(() => {
    if (!expanded) return
    if (before !== null && after !== null) return
    let cancelled = false
    setLoading(true)
    Promise.all([
      snapshot.beforeBlobId ? readBlobText(snapshot.beforeBlobId) : Promise.resolve(''),
      snapshot.afterBlobId ? readBlobText(snapshot.afterBlobId) : Promise.resolve(''),
    ])
      .then(([b, a]) => {
        if (cancelled) return
        setBefore(b)
        setAfter(a)
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [expanded, snapshot.beforeBlobId, snapshot.afterBlobId, before, after])

  // 計算 +M / −N summary,即使未展開也算(免一次拉 blob — 改成展開後才算實際)
  const stats = useMemo(() => {
    if (before === null || after === null) return null
    const parts = diffLines(before, after)
    let added = 0
    let removed = 0
    for (const part of parts) {
      const count = part.count ?? part.value.split('\n').length - 1
      if (part.added) added += count
      else if (part.removed) removed += count
    }
    return { added, removed, parts }
  }, [before, after])

  const filename = snapshot.filePath ? snapshot.filePath.split('/').pop() : '?'

  return (
    <div className="my-1 overflow-hidden rounded-md border border-bg-hover bg-bg-panel/40 text-xs">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-2 py-1.5 hover:bg-bg-hover"
        title={snapshot.filePath ?? undefined}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <FileText size={12} className="text-fg-muted" />
        <span className="truncate font-mono text-fg-base">{filename}</span>
        {stats && (
          <span className="ml-auto shrink-0 font-mono text-[10px]">
            <span className="text-success">+{stats.added}</span>
            <span className="text-fg-subtle"> / </span>
            <span className="text-error">−{stats.removed}</span>
          </span>
        )}
        {!stats && !expanded && (
          <span className="ml-auto shrink-0 text-[10px] text-fg-subtle">
            {t('diff.expand')}
          </span>
        )}
      </button>
      {expanded && (
        <div className="border-t border-bg-hover bg-bg-base">
          {loading && (
            <div className="px-2 py-3 text-center text-fg-subtle">{t('diff.loading')}</div>
          )}
          {err && (
            <div className="px-2 py-3 text-center text-error">
              {t('diff.error')}: {err}
            </div>
          )}
          {!loading && !err && stats && (
            <pre className="m-0 overflow-x-auto px-0 py-1 font-mono text-[11px] leading-tight">
              {stats.parts.flatMap((part, partIdx) => {
                const lines = part.value.split('\n')
                // 最後一個 empty 不顯(分割造成的尾巴)
                if (lines[lines.length - 1] === '') lines.pop()
                return lines.map((line, lineIdx) => {
                  const sign = part.added ? '+' : part.removed ? '−' : ' '
                  const cls = part.added
                    ? 'bg-success/10 text-success'
                    : part.removed
                      ? 'bg-error/10 text-error'
                      : 'text-fg-muted'
                  return (
                    <div
                      key={`${partIdx}-${lineIdx}`}
                      className={`px-2 ${cls}`}
                    >
                      <span className="mr-2 inline-block w-4 select-none text-center opacity-70">
                        {sign}
                      </span>
                      <span>{line || ' '}</span>
                    </div>
                  )
                })
              })}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
