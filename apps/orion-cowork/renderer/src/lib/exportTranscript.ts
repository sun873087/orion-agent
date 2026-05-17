/**
 * /export — 把全部 session 對話打包成資料夾匯出到 ~/Downloads。
 *
 * 結構:
 *   ~/Downloads/orion-cowork-export-YYYY-MM-DD/
 *     index.md                        — 所有 session 的 TOC
 *     001-{safe_title}/
 *       transcript.md                 — markdown 人讀
 *       transcript.json               — 結構化 JSON
 *       attachments/m{idx}-a{idx}.png — 圖片(以 base64 寫進 bundle)
 *
 * 走 listConversations + loadMessages + loadAttachment 三個既有 RPC,沒新後端。
 */

import JSZip from 'jszip'

import {
  getSessionWorkspace,
  listConversations,
  loadAttachment,
  loadMessages,
  type LoadedMessage,
  type SessionSummary,
} from '../api/agent'

type BundleFile = {
  relPath: string
  content: string
  encoding: 'utf8' | 'base64'
}

const MAX_TOOL_RESULT_CHARS = 800

/** Filename-safe:把 /, \\, : 等系統不允許的字元換成 dash。 */
function sanitizeFilename(name: string): string {
  return (
    name
      .replace(/[\/\\:*?"<>|]/g, '-')
      .replace(/\s+/g, '_')
      .replace(/^[-._]+|[-._]+$/g, '')
      .slice(0, 80) || 'untitled'
  )
}

function isoDate(): string {
  return new Date().toISOString().slice(0, 10)
}

/** Tool input 摘要:單行 JSON,過長截斷。 */
function summarizeToolInput(input: Record<string, unknown> | undefined): string {
  if (!input || Object.keys(input).length === 0) return ''
  const s = JSON.stringify(input)
  return s.length > 200 ? `${s.slice(0, 200)}…` : s
}

function summarizeToolResult(text: string | undefined): string {
  if (!text) return ''
  const trimmed = text.trim()
  return trimmed.length > MAX_TOOL_RESULT_CHARS
    ? `${trimmed.slice(0, MAX_TOOL_RESULT_CHARS)}\n…(已截斷,共 ${trimmed.length} 字)`
    : trimmed
}

/** 把單一 session 的 messages 轉成 markdown。 */
function formatMessagesAsMarkdown(
  messages: LoadedMessage[],
  sessionTitle: string,
  sessionId: string,
  createdAt: number,
): string {
  const out: string[] = []
  out.push(`# ${sessionTitle}`)
  out.push('')
  out.push(`- Session ID: \`${sessionId}\``)
  out.push(`- Created: ${new Date(createdAt * 1000).toISOString()}`)
  out.push(`- Exported: ${new Date().toISOString()}`)
  out.push('')
  out.push('---')
  out.push('')

  for (const m of messages) {
    // System / compact-summary 卡
    if (m.role === 'system' && m.kind === 'compact-summary') {
      out.push('---')
      out.push('')
      out.push('### 📋 對話壓縮摘要')
      out.push('')
      if (m.before_tokens && m.before_tokens > 0) {
        out.push(`_(壓縮前約 ${m.before_tokens} tokens)_`)
        out.push('')
      }
      out.push(
        m.text
          .split('\n')
          .map((l) => `> ${l}`)
          .join('\n'),
      )
      out.push('')
      out.push('_(以下到下個壓縮點之前的訊息,LLM 已看不到)_')
      out.push('')
      out.push('---')
      out.push('')
      continue
    }

    // user / assistant
    const isUser = m.role === 'user'
    const label = isUser ? '🧑 You' : '🤖 Orion'
    const compactedNote = m.compacted ? ' _(此段已壓縮,LLM 不再看到)_' : ''
    out.push(`## ${label}${compactedNote}`)
    out.push('')

    if (m.text && m.text.trim()) {
      out.push(m.text)
      out.push('')
    }

    // 附件圖片 ref
    if (m.attachments && m.attachments.length > 0) {
      for (let i = 0; i < m.attachments.length; i++) {
        const att = m.attachments[i]
        const ext = (att.media_type.split('/')[1] ?? 'png').replace(
          /[^a-z0-9]/gi,
          '',
        )
        const fname = `m${att.ref.message_index}-a${att.ref.attachment_index}.${ext}`
        out.push(`![attachment](./attachments/${fname})`)
        out.push('')
      }
    }

    // Tool calls 摘要(assistant only)
    if (!isUser && m.tool_calls && m.tool_calls.length > 0) {
      for (const tc of m.tool_calls) {
        const status = tc.status === 'error' ? ' ❌' : ' ✓'
        out.push(`> **[Tool] ${tc.tool_name}**${status}`)
        const inputStr = summarizeToolInput(tc.input)
        if (inputStr) {
          out.push(`> \`${inputStr}\``)
        }
        const resultStr = summarizeToolResult(tc.text)
        if (resultStr) {
          out.push('>')
          out.push(
            resultStr
              .split('\n')
              .map((l) => `> ${l}`)
              .join('\n'),
          )
        }
        out.push('')
      }
    }
  }

  return out.join('\n')
}

/** 從 dataURL 解出 base64 字串(去掉 prefix)。失敗回 null。 */
function dataUrlToBase64(dataUrl: string): { mediaType: string; b64: string } | null {
  const m = dataUrl.match(/^data:([^;]+);base64,(.+)$/)
  if (!m) return null
  return { mediaType: m[1], b64: m[2] }
}

/** 撈某 session 所有附件圖、轉成 BundleFile(base64 encoding)。 */
async function collectAttachments(
  sessionId: string,
  messages: LoadedMessage[],
  baseRelDir: string,
): Promise<BundleFile[]> {
  const files: BundleFile[] = []
  for (const m of messages) {
    if (!m.attachments?.length) continue
    for (const att of m.attachments) {
      try {
        const dataUrl = await loadAttachment(
          sessionId,
          att.ref.message_index,
          att.ref.attachment_index,
        )
        const decoded = dataUrlToBase64(dataUrl)
        if (!decoded) continue
        const ext = (decoded.mediaType.split('/')[1] ?? 'png').replace(
          /[^a-z0-9]/gi,
          '',
        )
        const fname = `m${att.ref.message_index}-a${att.ref.attachment_index}.${ext}`
        files.push({
          relPath: `${baseRelDir}/attachments/${fname}`,
          content: decoded.b64,
          encoding: 'base64',
        })
      } catch {
        // 個別附件失敗略過,不擋整個 export
      }
    }
  }
  return files
}

/** 組 index.md:所有 session 的 TOC。 */
function makeIndexMarkdown(
  sessions: Array<{ summary: SessionSummary; dirName: string; nMessages: number }>,
): string {
  const out: string[] = []
  out.push('# Orion Cowork — Full Export')
  out.push('')
  out.push(`Exported: ${new Date().toISOString()}`)
  out.push(`Sessions: ${sessions.length}`)
  out.push('')
  out.push('---')
  out.push('')
  out.push('## Sessions')
  out.push('')
  for (let i = 0; i < sessions.length; i++) {
    const { summary, dirName, nMessages } = sessions[i]
    const title = summary.title ?? '(Untitled)'
    const date = new Date(summary.created_at * 1000).toISOString().slice(0, 10)
    out.push(
      `${i + 1}. [${title}](./${dirName}/transcript.md) — ${summary.provider}/${summary.model} · ${nMessages} msg · ${date}`,
    )
  }
  out.push('')
  return out.join('\n')
}

/** Public entry — 跑 export 流程。
 *
 *  目的地優先序:
 *    1. 當前 session 的 resolved_cwd(對話的工作資料夾,session > project > app default)
 *    2. 若 session 沒有 workspace 或拿不到 → fallback ~/Downloads
 *
 *  寫完用 shellApi.revealInFinder 開檔案位置給使用者看到。完成回 path,失敗 throw。 */
export async function exportAllSessions(
  currentSessionId?: string | null,
): Promise<string | null> {
  const sessions = await listConversations()
  if (sessions.length === 0) {
    throw new Error('沒有任何對話可匯出')
  }

  // 先解析目的地 — 拿當前對話的工作資料夾;沒設 / 失敗就 fallback ~/Downloads
  let targetDir: string | undefined
  if (currentSessionId) {
    try {
      const ext = await getSessionWorkspace(currentSessionId)
      if (ext.resolved_cwd) targetDir = ext.resolved_cwd
    } catch {
      // 拿不到就走預設
    }
  }

  const bundleName = `orion-cowork-export-${isoDate()}`
  const files: BundleFile[] = []
  const indexEntries: Array<{
    summary: SessionSummary
    dirName: string
    nMessages: number
  }> = []

  // 依 created_at 從舊到新排(列表是最新優先,翻過來人讀順)
  const sortedSessions = [...sessions].sort(
    (a, b) => a.created_at - b.created_at,
  )

  for (let i = 0; i < sortedSessions.length; i++) {
    const sess = sortedSessions[i]
    const safeName = sanitizeFilename(sess.title ?? `session-${sess.session_id.slice(0, 8)}`)
    const dirName = `${String(i + 1).padStart(3, '0')}-${safeName}`

    let messages: LoadedMessage[] = []
    try {
      messages = await loadMessages(sess.session_id)
    } catch {
      // 跳過讀不到的
      continue
    }

    // markdown
    files.push({
      relPath: `${dirName}/transcript.md`,
      content: formatMessagesAsMarkdown(
        messages,
        sess.title ?? '(Untitled)',
        sess.session_id,
        sess.created_at,
      ),
      encoding: 'utf8',
    })

    // JSON(直接 dump,可程式化處理)
    files.push({
      relPath: `${dirName}/transcript.json`,
      content: JSON.stringify(
        {
          session_id: sess.session_id,
          title: sess.title,
          provider: sess.provider,
          model: sess.model,
          created_at: sess.created_at,
          n_messages: sess.n_messages,
          exported_at: new Date().toISOString(),
          messages,
        },
        null,
        2,
      ),
      encoding: 'utf8',
    })

    // 附件圖
    const attFiles = await collectAttachments(sess.session_id, messages, dirName)
    files.push(...attFiles)

    indexEntries.push({
      summary: sess,
      dirName,
      nMessages: messages.length,
    })
  }

  // index.md
  files.push({
    relPath: 'index.md',
    content: makeIndexMarkdown(indexEntries),
    encoding: 'utf8',
  })

  // 用 JSZip 打成單一 .zip 檔(內含 index.md + 各 session 子資料夾)
  const zip = new JSZip()
  for (const f of files) {
    if (f.encoding === 'base64') {
      zip.file(f.relPath, f.content, { base64: true })
    } else {
      zip.file(f.relPath, f.content)
    }
  }
  const zipB64 = await zip.generateAsync({
    type: 'base64',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
  })

  const zipFilename = `${bundleName}.zip`
  const savedPath = await window.dialog.saveFile(
    zipFilename,
    zipB64,
    'base64',
    targetDir,
  )
  if (savedPath) {
    // Reveal in Finder — highlight 那個 .zip 讓使用者看到
    void window.shellApi.revealInFinder(savedPath)
  }
  return savedPath
}
