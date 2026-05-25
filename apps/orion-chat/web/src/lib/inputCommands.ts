/**
 * 輸入框 `/` 指令與 `@` 提及的純邏輯(無 React / 無 i18n,方便單測)。
 *
 * - `/` slash:當前 session 的 client 動作(compact/plan/context/schedule)+ 動態 skills。
 * - `@` 提及:`@skill:` 引用 skill、`@file:` 引用 session workspace 檔;無前綴的 `@`
 *   兩者混合。送出時 buildSendPrefix() 把引用轉成 prompt 前綴讓 LLM 知道要載 skill / 讀檔。
 */

/** client 指令名(在 ChatView 端對應到 compact/plan/context/schedule 動作)。 */
export type ClientCommandName = '/compact' | '/plan' | '/context' | '/schedule'

export interface SlashCommand {
  name: string
  kind: 'client' | 'skill'
  /** client 指令的 i18n 說明 key */
  descKey?: string
  /** skill 的原始描述(來自後端) */
  desc?: string
}

export interface SkillRef {
  name: string
  description?: string
}

export interface MentionItem {
  kind: 'skill' | 'file'
  value: string
  label: string
  detail?: string
}

export interface MentionContext {
  mode: 'skill' | 'file' | 'any'
  query: string
  /** '@' 的 index */
  startIdx: number
  /** 游標 index */
  endIdx: number
}

export const CLIENT_COMMANDS: SlashCommand[] = [
  { name: '/compact', kind: 'client', descKey: 'chat.slash.compact' },
  { name: '/plan', kind: 'client', descKey: 'chat.slash.plan' },
  { name: '/context', kind: 'client', descKey: 'chat.slash.context' },
  { name: '/schedule', kind: 'client', descKey: 'chat.slash.schedule' },
]

const CLIENT_NAMES = new Set(CLIENT_COMMANDS.map((c) => c.name))

export function isClientCommand(name: string): name is ClientCommandName {
  return CLIENT_NAMES.has(name)
}

/** client 指令需要 active session;draft / 無 session 時只給 skills。 */
export function buildSlashCommands(
  skills: SkillRef[],
  hasSession: boolean,
): SlashCommand[] {
  const client = hasSession ? CLIENT_COMMANDS : []
  const skillCmds: SlashCommand[] = skills.map((s) => ({
    name: `/${s.name}`,
    kind: 'skill',
    desc: s.description,
  }))
  return [...client, ...skillCmds]
}

/**
 * slash popover 的 query — 只在「整個輸入以 `/` 開頭、單行、還沒打空白」時有效。
 * 打了空白(開始輸入內文 / 參數)就收起 popover。
 */
export function slashQuery(text: string): string | null {
  if (!text.startsWith('/') || text.includes('\n')) return null
  if (text.includes(' ')) return null
  return text.slice(1)
}

export function filterSlash(
  commands: SlashCommand[],
  query: string,
): SlashCommand[] {
  const q = query.toLowerCase()
  return commands.filter((c) => c.name.slice(1).toLowerCase().includes(q))
}

/**
 * 偵測游標所在的 `@` token。中間有空白即非提及;`@` 前須為行首或空白
 * (避免 email 等誤觸)。回傳 mode + query + 起訖,供取代用。
 */
export function detectMention(
  text: string,
  cursor: number,
): MentionContext | null {
  let i = cursor - 1
  while (i >= 0) {
    const ch = text[i]
    if (ch === '@') break
    if (ch === ' ' || ch === '\n' || ch === '\t') return null
    i--
  }
  if (i < 0 || text[i] !== '@') return null
  if (i > 0 && !/\s/.test(text[i - 1] ?? '')) return null

  const token = text.slice(i + 1, cursor)
  if (token.startsWith('skill:')) {
    return { mode: 'skill', query: token.slice(6), startIdx: i, endIdx: cursor }
  }
  if (token.startsWith('file:')) {
    return { mode: 'file', query: token.slice(5), startIdx: i, endIdx: cursor }
  }
  return { mode: 'any', query: token, startIdx: i, endIdx: cursor }
}

export function filterMentions(
  ctx: MentionContext,
  skills: SkillRef[],
  files: string[],
): MentionItem[] {
  const q = ctx.query.toLowerCase()
  const skillItems: MentionItem[] = skills
    .filter((s) => s.name.toLowerCase().includes(q))
    .map((s) => ({
      kind: 'skill',
      value: s.name,
      label: s.name,
      detail: s.description,
    }))
  const fileItems: MentionItem[] = files
    .filter((f) => f.toLowerCase().includes(q))
    .map((f) => ({ kind: 'file', value: f, label: f }))
  if (ctx.mode === 'skill') return skillItems
  if (ctx.mode === 'file') return fileItems
  return [...skillItems, ...fileItems]
}

export function mentionToken(item: MentionItem): string {
  return item.kind === 'skill' ? `@skill:${item.value}` : `@file:${item.value}`
}

/** 把游標處的 `@token` 換成正式 mention token(後加空白),回新文字 + 新游標。 */
export function applyMention(
  text: string,
  ctx: MentionContext,
  item: MentionItem,
): { text: string; cursor: number } {
  const before = text.slice(0, ctx.startIdx)
  const after = text.slice(ctx.endIdx)
  const insert = `${mentionToken(item)} `
  return { text: before + insert + after, cursor: (before + insert).length }
}

/**
 * 掃 @skill: / @file: token,生成送給 LLM 的 prompt 前綴(對齊 cowork 做法)。
 * 沒有引用回空字串。
 */
export function buildSendPrefix(text: string): string {
  const skills = [...text.matchAll(/(?:^|\s)@skill:([\w-]+)/g)].map((m) => m[1]!)
  const files = [...text.matchAll(/(?:^|\s)@file:(\S+)/g)].map((m) => m[1]!)
  const uniqSkills = [...new Set(skills)]
  const uniqFiles = [...new Set(files)]
  const parts: string[] = []
  if (uniqSkills.length > 0) {
    parts.push(
      `[User referenced skills: ${uniqSkills.join(', ')}. Load them via the Skill tool.]`,
    )
  }
  if (uniqFiles.length > 0) {
    parts.push(
      `[User referenced files: ${uniqFiles.join(', ')}. Read them from the workspace with the Read tool as needed.]`,
    )
  }
  return parts.join('\n')
}
