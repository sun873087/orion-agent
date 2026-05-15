/**
 * 一行內顯示的關鍵參數(claude.ai 風格的 chip)。
 * Bash → command 第一行、Read/Write/Edit → basename、Glob/Grep → pattern、WebFetch → host。
 * 不存在則回 null,讓 caller 不渲染 chip。
 */
export function summarizeToolInput(
  toolName: string,
  input: Record<string, unknown>,
): string | null {
  if (toolName === 'Bash' && typeof input['command'] === 'string') {
    const cmd = input['command']
    const firstLine = cmd.split('\n', 1)[0] ?? ''
    return firstLine.length > 60 ? firstLine.slice(0, 60) + '…' : firstLine
  }
  if (
    (toolName === 'Read' ||
      toolName === 'Write' ||
      toolName === 'Edit' ||
      toolName === 'NotebookEdit') &&
    typeof input['file_path'] === 'string'
  ) {
    const fp = input['file_path']
    const basename = fp.split('/').pop() ?? fp
    return basename
  }
  if (
    (toolName === 'Glob' || toolName === 'Grep') &&
    typeof input['pattern'] === 'string'
  ) {
    return input['pattern']
  }
  if (toolName === 'WebFetch' && typeof input['url'] === 'string') {
    try {
      return new URL(input['url']).host
    } catch {
      return input['url']
    }
  }
  if (toolName === 'Skill' && typeof input['name'] === 'string') {
    return input['name']
  }
  return null
}
