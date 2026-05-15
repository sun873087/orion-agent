/**
 * 把 tool input 渲染得好看些 — 按 tool 名特殊處理常見的:Bash 顯示原始 command(保留換行)、
 * Read/Write/Edit/Glob/Grep/WebFetch 拆 path / pattern / content 顯示。其他 fallback JSON。
 *
 * 比起 raw `JSON.stringify` — long bash script 不會被 `\n` 字面值塞爆。
 */
interface Props {
  toolName: string
  input: Record<string, unknown>
}

export function ToolInputView({ toolName, input }: Props) {
  // ─── Bash:command 直接 pre,保留換行 ────────────────────────────────
  if (toolName === 'Bash' && typeof input['command'] === 'string') {
    const cmd = input['command']
    const otherKeys = Object.keys(input).filter((k) => k !== 'command')
    return (
      <div className="space-y-2">
        <CodeBlock language="bash" content={cmd} />
        {otherKeys.length > 0 && (
          <KeyValueRows
            data={Object.fromEntries(otherKeys.map((k) => [k, input[k]]))}
          />
        )}
      </div>
    )
  }

  // ─── Read:檔路徑 + offset/limit ────────────────────────────────────
  if (toolName === 'Read' && typeof input['file_path'] === 'string') {
    return (
      <KeyValueRows
        data={{
          path: input['file_path'],
          ...(input['offset'] != null ? { offset: input['offset'] } : {}),
          ...(input['limit'] != null ? { limit: input['limit'] } : {}),
        }}
      />
    )
  }

  // ─── Write:path + content(多行 → code block)─────────────────────
  if (
    toolName === 'Write' &&
    typeof input['file_path'] === 'string' &&
    typeof input['content'] === 'string'
  ) {
    return (
      <div className="space-y-2">
        <KeyValueRows data={{ path: input['file_path'] }} />
        <CodeBlock content={input['content']} />
      </div>
    )
  }

  // ─── Edit:path + old/new(多行 → 雙 code block)────────────────────
  if (toolName === 'Edit' && typeof input['file_path'] === 'string') {
    const oldStr = input['old_string']
    const newStr = input['new_string']
    return (
      <div className="space-y-2">
        <KeyValueRows data={{ path: input['file_path'] }} />
        {typeof oldStr === 'string' && (
          <div>
            <div className="text-[11px] text-claude-textFaint mb-1">old:</div>
            <CodeBlock content={oldStr} />
          </div>
        )}
        {typeof newStr === 'string' && (
          <div>
            <div className="text-[11px] text-claude-textFaint mb-1">new:</div>
            <CodeBlock content={newStr} />
          </div>
        )}
      </div>
    )
  }

  // ─── Glob / Grep:pattern + path ────────────────────────────────────
  if ((toolName === 'Glob' || toolName === 'Grep') && input['pattern']) {
    return (
      <KeyValueRows
        data={{
          pattern: input['pattern'],
          ...(input['path'] != null ? { path: input['path'] } : {}),
          ...(input['include'] != null ? { include: input['include'] } : {}),
        }}
      />
    )
  }

  // ─── WebFetch:url + prompt(若有)───────────────────────────────
  if (toolName === 'WebFetch' && typeof input['url'] === 'string') {
    return (
      <div className="space-y-2">
        <KeyValueRows data={{ url: input['url'] }} />
        {typeof input['prompt'] === 'string' && (
          <CodeBlock content={input['prompt']} />
        )}
      </div>
    )
  }

  // ─── Fallback:JSON ────────────────────────────────────────────────
  return (
    <pre className="text-[12px] overflow-x-auto whitespace-pre-wrap break-all">
      {JSON.stringify(input, null, 2)}
    </pre>
  )
}

function CodeBlock({
  content,
  language,
}: {
  content: string
  language?: string
}) {
  return (
    <pre className="text-[12px] bg-claude-code text-claude-codeText border border-claude-borderSoft rounded-md px-3 py-2 overflow-x-auto whitespace-pre max-h-80">
      {language && (
        <div className="text-[10px] uppercase tracking-wider text-claude-textFaint mb-1">
          {language}
        </div>
      )}
      <code>{content}</code>
    </pre>
  )
}

function KeyValueRows({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data)
  if (entries.length === 0) return null
  return (
    <div className="text-[12px] space-y-0.5">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="text-claude-textFaint min-w-[60px] shrink-0">
            {k}
          </span>
          <span className="font-mono break-all">{formatValue(v)}</span>
        </div>
      ))}
    </div>
  )
}

function formatValue(v: unknown): string {
  if (typeof v === 'string') return v
  if (v === null || v === undefined) return String(v)
  return JSON.stringify(v)
}
