/**
 * Renderer-side wrapper of window.agent.call。
 *
 * 對外:
 *   - createConversation({ provider, model }) → session_id
 *   - sendPrompt(session_id, prompt, onEvent) → 等 turn 完成
 *   - abort(session_id)
 */

export type SidecarEvent =
  | { event: 'text_delta'; data: { text: string } }
  | { event: 'thinking_delta'; data: { text: string } }
  | { event: 'turn_complete'; data: Record<string, never> }
  | {
      event: 'tool_progress'
      data: { tool_name: string; tool_use_id: string; progress: unknown }
    }
  | {
      event: 'tool_error'
      data: { tool_name: string; tool_use_id: string; message: string }
    }
  | {
      event: 'tool_result'
      data: { tool_name: string; tool_use_id: string; is_error: boolean; text: string }
    }
  | { event: 'loop_terminated'; data: { reason: string; total_turns: number } }
  | {
      event: 'tool_approval_request'
      data: { tool_use_id: string; tool_name: string; input: Record<string, unknown> }
    }
  | {
      event: 'ask_user_question'
      data: { request_id: string; questions: AskQuestion[] }
    }
  | { event: 'compact_started'; data: { session_id: string } }
  | {
      event: 'compact_complete'
      data: {
        summary: string
        before_tokens: number
        after_tokens: number
        auto?: boolean
        skipped?: boolean
      }
    }
  | {
      event: 'truncate_complete'
      data: { session_id: string; removed: number; resend: boolean }
    }
  | { event: string; data?: unknown; final?: boolean }

export type AskOption = { label: string; description?: string }
export type AskQuestion = {
  question: string
  header?: string
  options: AskOption[]
  multi_select: boolean
}

export type PermissionMode = 'ask' | 'act'

export async function createConversation(
  provider = 'anthropic',
  model = 'claude-sonnet-4-6',
  opts?: { projectId?: string | null; workspaceDir?: string | null },
): Promise<string> {
  let sessionId = ''
  const params: Record<string, unknown> = { provider, model }
  if (opts?.projectId) params.project_id = opts.projectId
  if (opts?.workspaceDir) params.workspace_dir = opts.workspaceDir
  await window.agent.call('conversation.create', params, (frame) => {
    const data = (frame.data ?? {}) as { session_id?: string }
    if (data.session_id) sessionId = data.session_id
  })
  if (!sessionId) throw new Error('conversation.create returned no session_id')
  return sessionId
}

export type SessionExt = {
  session_id: string
  workspace_dir: string | null
  project_id: string | null
  /** Session 的最終 cwd(session override > project > app default)。
   *  /export 等想實際寫檔到對話工作目錄的 caller 用這個。 */
  resolved_cwd: string | null
}

export async function getSessionWorkspace(sessionId: string): Promise<SessionExt> {
  let ext: SessionExt = {
    session_id: sessionId,
    workspace_dir: null,
    project_id: null,
    resolved_cwd: null,
  }
  await window.agent.call(
    'conversation.get_workspace',
    { session_id: sessionId },
    (frame) => {
      if (frame.event === 'session_ext' && frame.data) {
        ext = frame.data as SessionExt
      }
    },
  )
  return ext
}

export async function setSessionWorkspace(
  sessionId: string,
  workspaceDir: string | null,
): Promise<void> {
  await window.agent.call(
    'conversation.set_workspace',
    { session_id: sessionId, workspace_dir: workspaceDir },
    () => {},
  )
}

export async function setSessionProject(
  sessionId: string,
  projectId: string | null,
): Promise<void> {
  await window.agent.call(
    'conversation.set_project',
    { session_id: sessionId, project_id: projectId },
    () => {},
  )
}

export type Project = {
  id: string
  name: string
  description: string | null
  workspace_dir: string | null
  custom_instructions: string | null
  created_at: number
}

export async function listProjects(): Promise<Project[]> {
  let projects: Project[] = []
  await window.agent.call('project.list', {}, (frame) => {
    if (frame.event === 'project_list' && frame.data) {
      const d = frame.data as { projects: Project[] }
      projects = d.projects ?? []
    }
  })
  return projects
}

export async function getProject(
  projectId: string,
): Promise<{ project: Project; session_ids: string[] } | null> {
  let out: { project: Project; session_ids: string[] } | null = null
  await window.agent.call('project.get', { project_id: projectId }, (frame) => {
    if (frame.event === 'project' && frame.data) {
      const d = frame.data as { project: Project; session_ids?: string[] }
      out = { project: d.project, session_ids: d.session_ids ?? [] }
    }
  })
  return out
}

export async function createProject(input: {
  name: string
  description?: string | null
  workspace_dir?: string | null
  custom_instructions?: string | null
}): Promise<Project> {
  let proj: Project | null = null
  await window.agent.call('project.create', input as Record<string, unknown>, (frame) => {
    if (frame.event === 'project' && frame.data) {
      const d = frame.data as { project: Project }
      proj = d.project
    }
  })
  if (!proj) throw new Error('project.create returned no project')
  return proj
}

export async function updateProject(
  projectId: string,
  input: Partial<{
    name: string
    description: string | null
    workspace_dir: string | null
    custom_instructions: string | null
  }>,
): Promise<void> {
  await window.agent.call(
    'project.update',
    { project_id: projectId, ...input } as Record<string, unknown>,
    () => {},
  )
}

export async function deleteProject(projectId: string): Promise<void> {
  await window.agent.call('project.delete', { project_id: projectId }, () => {})
}

export type MemoryType = 'user' | 'feedback' | 'project' | 'reference'

export type MemoryListItem = {
  filename: string
  name: string
  description: string
  type: MemoryType | null
  expires_at: string | null
}

export type Memory = MemoryListItem & {
  body: string
}

export async function listMemories(projectId?: string | null): Promise<{
  memory_dir: string
  memories: MemoryListItem[]
}> {
  let out: { memory_dir: string; memories: MemoryListItem[] } = {
    memory_dir: '',
    memories: [],
  }
  const params: Record<string, unknown> = {}
  if (projectId) params.project_id = projectId
  await window.agent.call('memory.list', params, (frame) => {
    if (frame.event === 'memory_list' && frame.data) {
      out = frame.data as { memory_dir: string; memories: MemoryListItem[] }
    }
  })
  return out
}

export async function getMemory(filename: string, projectId?: string | null): Promise<Memory | null> {
  let m: Memory | null = null
  const params: Record<string, unknown> = { filename }
  if (projectId) params.project_id = projectId
  await window.agent.call('memory.get', params, (frame) => {
    if (frame.event === 'memory' && frame.data) {
      const d = frame.data as { memory: Memory }
      m = d.memory
    }
  })
  return m
}

export async function writeMemory(input: {
  filename?: string | null
  name: string
  description: string
  type: MemoryType
  body: string
  expires_at?: string | null
  project_id?: string | null
}): Promise<{ filename: string; memory: Memory | null }> {
  let out: { filename: string; memory: Memory | null } = { filename: '', memory: null }
  await window.agent.call('memory.write', input as Record<string, unknown>, (frame) => {
    if (frame.event === 'memory' && frame.data) {
      const d = frame.data as { memory: Memory | null; filename: string }
      out = d
    }
  })
  return out
}

export async function deleteMemory(filename: string, projectId?: string | null): Promise<void> {
  const params: Record<string, unknown> = { filename }
  if (projectId) params.project_id = projectId
  await window.agent.call('memory.delete', params, () => {})
}

export type SkillSource = 'bundled' | 'system' | 'user' | 'other' | 'unknown'

export type SkillListItem = {
  name: string
  description: string
  filename: string
  source: SkillSource
  editable: boolean
  source_path: string | null
}

export type Skill = SkillListItem & {
  body: string
}

export async function listSkills(projectId?: string | null): Promise<{
  user_skills_dir: string
  skills: SkillListItem[]
}> {
  let out: { user_skills_dir: string; skills: SkillListItem[] } = {
    user_skills_dir: '',
    skills: [],
  }
  const params: Record<string, unknown> = {}
  if (projectId) params.project_id = projectId
  await window.agent.call('skill.list', params, (frame) => {
    if (frame.event === 'skill_list' && frame.data) {
      out = frame.data as { user_skills_dir: string; skills: SkillListItem[] }
    }
  })
  return out
}

export async function getSkill(name: string, projectId?: string | null): Promise<Skill | null> {
  let s: Skill | null = null
  const params: Record<string, unknown> = { name }
  if (projectId) params.project_id = projectId
  await window.agent.call('skill.get', params, (frame) => {
    if (frame.event === 'skill' && frame.data) {
      const d = frame.data as { skill: Skill }
      s = d.skill
    }
  })
  return s
}

export async function writeSkill(input: {
  filename?: string | null
  name: string
  description: string
  body: string
  rename_from?: string | null
  project_id?: string | null
}): Promise<void> {
  await window.agent.call('skill.write', input as Record<string, unknown>, () => {})
}

export async function deleteSkill(filename: string, projectId?: string | null): Promise<void> {
  const params: Record<string, unknown> = { filename }
  if (projectId) params.project_id = projectId
  await window.agent.call('skill.delete', params, () => {})
}

export type ImportedSkill = { name: string; filename: string; targetDir: string }

/** 匯入外部 skill 資料夾(含 SKILL.md + 附帶檔)— sidecar copytree 整段。
 *  ALREADY_EXISTS error 時 caller 可加 overwrite=true 再呼一次覆蓋。 */
export async function importSkillFolder(
  sourcePath: string,
  opts?: { projectId?: string | null; filename?: string; overwrite?: boolean },
): Promise<ImportedSkill> {
  let result: ImportedSkill | null = null
  let errMsg: string | null = null
  let errCode: string | null = null
  const params: Record<string, unknown> = { source_path: sourcePath }
  if (opts?.projectId) params.project_id = opts.projectId
  if (opts?.filename) params.filename = opts.filename
  if (opts?.overwrite) params.overwrite = true
  await window.agent.call('skill.import_folder', params, (frame) => {
    const f = frame as {
      event?: string
      data?: Record<string, unknown>
      error?: { code?: string; message?: string }
    }
    if (f.event === 'skill_imported' && f.data) {
      result = {
        name: String(f.data.name ?? ''),
        filename: String(f.data.filename ?? ''),
        targetDir: String(f.data.target_dir ?? ''),
      }
    } else if (f.event === 'error' && f.data) {
      errCode = typeof f.data.code === 'string' ? f.data.code : null
      errMsg = typeof f.data.message === 'string' ? f.data.message : null
    }
  })
  if (!result) {
    const err = new Error(errMsg ?? 'import failed')
    ;(err as Error & { code?: string }).code = errCode ?? undefined
    throw err
  }
  return result
}

export async function getPrefs(): Promise<Record<string, string>> {
  let out: Record<string, string> = {}
  await window.agent.call('prefs.get_all', {}, (frame) => {
    if (frame.event === 'prefs' && frame.data) {
      const d = frame.data as { prefs: Record<string, string> }
      out = d.prefs ?? {}
    }
  })
  return out
}

export async function setPref(key: string, value: string | null): Promise<void> {
  await window.agent.call('prefs.set', { key, value }, () => {})
}

export type Attachment = {
  media_type: string  // "image/png" / "image/jpeg" / ...
  data: string        // base64-encoded(no data: prefix)
  /** Frontend-only:給 UI 預覽用,sidecar 忽略。 */
  preview_url?: string
  /** Frontend-only:檔名,只顯示用。 */
  filename?: string
}

export async function sendPrompt(
  sessionId: string,
  prompt: string,
  onEvent: (ev: SidecarEvent) => void,
  attachments?: Attachment[],
  permissionMode?: PermissionMode,
  opts?: {
    autoCompactEnabled?: boolean
    autoCompactThreshold?: number
    locale?: string
    summaryProvider?: string | null
    summaryModel?: string | null
  },
): Promise<void> {
  await window.agent.call(
    'conversation.send',
    {
      session_id: sessionId,
      prompt,
      permission_mode: permissionMode ?? 'act',
      auto_compact_enabled: opts?.autoCompactEnabled ?? true,
      auto_compact_threshold: opts?.autoCompactThreshold ?? 0.8,
      locale: opts?.locale,
      summary_provider: opts?.summaryProvider ?? undefined,
      summary_model: opts?.summaryModel ?? undefined,
      attachments: (attachments ?? []).map((a) => ({
        media_type: a.media_type,
        data: a.data,
      })),
    },
    (frame) => {
      onEvent(frame as unknown as SidecarEvent)
    },
  )
}

export type ContextCategory = { name: string; tokens: number }
export type ContextToolDetail = { name: string; server: string; tokens: number }
export type ContextSkillDetail = { name: string; source: string; tokens: number }
export type ContextBreakdown = {
  sessionId: string
  provider: string
  model: string
  maxContextTokens: number
  totalUsedTokens: number
  categories: ContextCategory[]
  mcpToolsDetail: ContextToolDetail[]
  skillsDetail: ContextSkillDetail[]
}

/** /context — 拉當前 session 的 context window 分配(全 sidecar 本機計算,不打 LLM)。
 *  autoCompactThreshold 應由 caller 從 settings 帶進來,否則 sidecar 用 conv 內的
 *  舊值或預設 0.8,跟 UI 顯示的可能不一致。 */
export async function getContextBreakdown(
  sessionId: string,
  opts?: { autoCompactThreshold?: number },
): Promise<ContextBreakdown | null> {
  let out: ContextBreakdown | null = null
  const params: Record<string, unknown> = { session_id: sessionId }
  if (typeof opts?.autoCompactThreshold === 'number') {
    params.auto_compact_threshold = opts.autoCompactThreshold
  }
  await window.agent.call(
    'conversation.context_breakdown',
    params,
    (frame) => {
      const f = frame as { event?: string; data?: Record<string, unknown> }
      if (f.event !== 'context_breakdown' || !f.data) return
      const d = f.data
      const cats = Array.isArray(d.categories) ? (d.categories as ContextCategory[]) : []
      const mcp = Array.isArray(d.mcp_tools_detail)
        ? (d.mcp_tools_detail as ContextToolDetail[])
        : []
      const skills = Array.isArray(d.skills_detail)
        ? (d.skills_detail as ContextSkillDetail[])
        : []
      out = {
        sessionId: String(d.session_id ?? sessionId),
        provider: String(d.provider ?? ''),
        model: String(d.model ?? ''),
        maxContextTokens:
          typeof d.max_context_tokens === 'number' ? d.max_context_tokens : 0,
        totalUsedTokens:
          typeof d.total_used_tokens === 'number' ? d.total_used_tokens : 0,
        categories: cats,
        mcpToolsDetail: mcp,
        skillsDetail: skills,
      }
    },
  )
  return out
}

/** 從指定 message_index 起 truncate;有 resendText 就重跑 send,沒給就純 delete。
 *  Cache 影響:被刪 message 以後的 prefix 變了 → BP3 / BP4 cache 失效,要重寫。 */
export async function truncateConversation(
  sessionId: string,
  messageIndex: number,
  onEvent: (ev: SidecarEvent) => void,
  opts?: {
    resendText?: string
    resendImages?: Attachment[]
    permissionMode?: PermissionMode
    locale?: string
  },
): Promise<void> {
  const params: Record<string, unknown> = {
    session_id: sessionId,
    message_index: messageIndex,
  }
  if (opts?.resendText) params.resend_text = opts.resendText
  if (opts?.resendImages?.length) {
    params.resend_images = opts.resendImages.map((a) => ({
      media_type: a.media_type,
      data: a.data,
    }))
  }
  if (opts?.permissionMode) params.permission_mode = opts.permissionMode
  if (opts?.locale) params.locale = opts.locale
  await window.agent.call('conversation.truncate', params, (frame) => {
    onEvent(frame as unknown as SidecarEvent)
  })
}

/** 手動觸發對話壓縮 — UI 攔到 /compact 後呼叫。force=true 跳過 threshold 直接壓。
 *  locale 控制摘要語系(zh-TW / zh-CN / ja / en),sidecar 傳給 SDK 摘要 prompt。 */
export async function compactConversation(
  sessionId: string,
  onEvent: (ev: SidecarEvent) => void,
  opts?: {
    force?: boolean
    locale?: string
    summaryProvider?: string | null
    summaryModel?: string | null
  },
): Promise<void> {
  await window.agent.call(
    'conversation.compact',
    {
      session_id: sessionId,
      force: opts?.force ?? true,
      locale: opts?.locale,
      summary_provider: opts?.summaryProvider ?? undefined,
      summary_model: opts?.summaryModel ?? undefined,
    },
    (frame) => {
      onEvent(frame as unknown as SidecarEvent)
    },
  )
}

export async function abort(sessionId: string): Promise<void> {
  await window.agent.call('conversation.abort', { session_id: sessionId }, () => {})
}

/** Ask 模式下:回 tool approval 決定。decision='allow' 或 'deny'。 */
export async function sendToolApproval(
  toolUseId: string,
  decision: 'allow' | 'deny',
  reason?: string,
): Promise<void> {
  await window.agent.call(
    'conversation.tool_approval',
    { tool_use_id: toolUseId, decision, reason: reason ?? '' },
    () => {},
  )
}

/** 回 AskUserQuestion 答案 — answers map question text → chosen label / free text。 */
export async function sendAskUserReply(
  requestId: string,
  answers: Record<string, string>,
): Promise<void> {
  await window.agent.call(
    'conversation.ask_user_reply',
    { request_id: requestId, answers },
    () => {},
  )
}

export type ConversationStats = {
  sessionId: string
  provider: string
  model: string
  turns: number
  toolCalls: number
  toolErrors: number
  cumulative: TokenBucket
  lastTurn: TokenBucket
  contextUsed: number
  contextMax: number
  cacheHitRate: number
}

export type TokenBucket = {
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheCreationTokens: number
  reasoningTokens: number
  costUsd: number
}

function _readBucket(d: Record<string, unknown> | undefined): TokenBucket {
  const o = (d ?? {}) as Record<string, unknown>
  const n = (k: string): number => (typeof o[k] === 'number' ? (o[k] as number) : 0)
  return {
    inputTokens: n('input_tokens'),
    outputTokens: n('output_tokens'),
    cacheReadTokens: n('cache_read_tokens'),
    cacheCreationTokens: n('cache_creation_tokens'),
    reasoningTokens: n('reasoning_tokens'),
    costUsd: n('cost_usd'),
  }
}

/** 拉 session 的 cost / context / cache stats(每次 turn 結束後 refresh 一次)。 */
export async function getConversationStats(
  sessionId: string,
): Promise<ConversationStats | null> {
  let out: ConversationStats | null = null
  await window.agent.call(
    'conversation.stats',
    { session_id: sessionId },
    (frame) => {
      const f = frame as { event?: string; data?: Record<string, unknown> }
      if (f.event !== 'stats' || !f.data) return
      const d = f.data
      out = {
        sessionId: String(d.session_id ?? sessionId),
        provider: String(d.provider ?? ''),
        model: String(d.model ?? ''),
        turns: typeof d.turns === 'number' ? d.turns : 0,
        toolCalls: typeof d.tool_calls === 'number' ? d.tool_calls : 0,
        toolErrors: typeof d.tool_errors === 'number' ? d.tool_errors : 0,
        cumulative: _readBucket(d.cumulative as Record<string, unknown> | undefined),
        lastTurn: _readBucket(d.last_turn as Record<string, unknown> | undefined),
        contextUsed: typeof d.context_used === 'number' ? d.context_used : 0,
        contextMax: typeof d.context_max === 'number' ? d.context_max : 0,
        cacheHitRate: typeof d.cache_hit_rate === 'number' ? d.cache_hit_rate : 0,
      }
    },
  )
  return out
}

/**
 * 中途切 Ask / Act mode — sidecar 立刻把 in-flight turn 的 can_use_tool gate
 * 切過去;若切到 'act' 還會 auto-resolve 所有等中的 approval / ask futures。
 */
export async function setPermissionMode(
  sessionId: string,
  mode: PermissionMode,
): Promise<void> {
  await window.agent.call(
    'conversation.set_permission_mode',
    { session_id: sessionId, mode },
    () => {},
  )
}

export type PermissionScope = 'global' | 'project'

export type PermissionPolicy = {
  scope: PermissionScope
  allow: string[]
  deny: string[]
}

/** 讀單一 scope 的 policy。Project scope 需要 workspaceDir。 */
export async function getPermissions(
  scope: PermissionScope,
  workspaceDir?: string | null,
): Promise<PermissionPolicy> {
  let out: PermissionPolicy = { scope, allow: [], deny: [] }
  const params: Record<string, unknown> = { scope }
  if (workspaceDir) params.workspace_dir = workspaceDir
  await window.agent.call('permissions.get', params, (frame) => {
    const d = (frame.data ?? {}) as { scope?: string; allow?: string[]; deny?: string[] }
    if (d.scope === 'global' || d.scope === 'project') {
      out = {
        scope: d.scope,
        allow: Array.isArray(d.allow) ? d.allow : [],
        deny: Array.isArray(d.deny) ? d.deny : [],
      }
    }
  })
  return out
}

// ─── STT ──────────────────────────────────────────────────────────────────

export type SttModel = {
  id: string
  label: string
  pricing_per_minute_usd?: number
  recommended?: boolean
  notes?: string
}

export type SttProviderEntry = {
  id: string
  label: string
  models: SttModel[]
  api_key_configured: boolean
}

export type SttCatalog = {
  providers: SttProviderEntry[]
}

/** 拉 STT catalog(來自 orion-model)+ 各家 API key 是否設定。給 Settings UI 用。 */
export async function getSttStatus(): Promise<SttCatalog> {
  let out: SttCatalog = { providers: [] }
  await window.agent.call('stt.status', {}, (frame) => {
    const d = (frame.data ?? {}) as { providers?: SttProviderEntry[] }
    if (Array.isArray(d.providers)) {
      out = {
        providers: d.providers.map((p) => ({
          id: p.id,
          label: p.label,
          models: Array.isArray(p.models) ? p.models : [],
          api_key_configured: !!p.api_key_configured,
        })),
      }
    }
  })
  return out
}

export type SttResult = {
  text: string
  provider: string
  model: string
  durationSeconds: number | null
  costUsd: number | null
}

/** 上傳錄音 base64 → 回 transcript + estimated cost。可能 throw(沒 key / API 失敗)。
 *  durationSeconds 由前端錄音時量;後端用 catalog pricing × duration 算 cost。 */
export async function sttTranscribe(
  provider: 'openai' | 'google',
  audioBase64: string,
  mimeType: string,
  locale: string,
  model?: string,
  durationSeconds?: number,
): Promise<SttResult> {
  let result: SttResult = {
    text: '',
    provider,
    model: model ?? '',
    durationSeconds: durationSeconds ?? null,
    costUsd: null,
  }
  let errMsg: string | null = null
  const params: Record<string, unknown> = {
    provider,
    audio_base64: audioBase64,
    mime_type: mimeType,
    locale,
  }
  if (provider === 'openai' && model) params.model = model
  if (durationSeconds != null) params.duration_seconds = durationSeconds
  await window.agent.call(
    'stt.transcribe',
    params,
    (frame) => {
      const f = frame as { event?: string; data?: Record<string, unknown>; error?: { message?: string } }
      if (f.error?.message) errMsg = f.error.message
      else if (f.event === 'error' && typeof f.data?.message === 'string') errMsg = f.data.message as string
      else if (f.event === 'transcribed' && f.data) {
        const d = f.data
        result = {
          text: typeof d.text === 'string' ? d.text : '',
          provider: typeof d.provider === 'string' ? d.provider : provider,
          model: typeof d.model === 'string' ? d.model : (model ?? ''),
          durationSeconds: typeof d.duration_seconds === 'number' ? d.duration_seconds : null,
          costUsd: typeof d.cost_usd === 'number' ? d.cost_usd : null,
        }
      }
    },
  )
  if (errMsg) throw new Error(errMsg)
  return result
}

/** 覆寫單一 scope 的 policy(整批替換,非 patch)。 */
export async function setPermissions(
  scope: PermissionScope,
  allow: string[],
  deny: string[],
  workspaceDir?: string | null,
): Promise<void> {
  const params: Record<string, unknown> = { scope, allow, deny }
  if (workspaceDir) params.workspace_dir = workspaceDir
  await window.agent.call('permissions.set', params, () => {})
}

export type ModelCatalog = {
  providers: Array<{
    id: string
    label: string
    models: Array<{
      id: string
      label: string
      max_context_tokens?: number
      supports_reasoning?: boolean
      pricing?: Record<string, number>
    }>
    api_key_configured: boolean
  }>
}

export async function fetchModels(): Promise<ModelCatalog> {
  let result: ModelCatalog | null = null
  await window.agent.call('models.list', {}, (frame) => {
    if (frame.event === 'models' && frame.data) {
      result = frame.data as ModelCatalog
    }
  })
  if (!result) throw new Error('models.list returned no data')
  return result
}

export type SessionSummary = {
  session_id: string
  provider: string
  model: string
  title: string | null
  created_at: number
  n_messages: number
}

export async function listConversations(): Promise<SessionSummary[]> {
  let result: SessionSummary[] = []
  await window.agent.call('conversation.list', {}, (frame) => {
    if (frame.event === 'conversation_list' && frame.data) {
      const data = frame.data as { sessions: SessionSummary[] }
      result = data.sessions ?? []
    }
  })
  return result
}

export type SearchHit = {
  session_id: string
  title: string | null
  provider: string
  model: string
  created_at: number
  match_count: number
  snippet: string
}

/** 跨 session 全文搜尋。query 空字串時直接回 [],不打 sidecar。 */
export async function searchConversations(query: string): Promise<SearchHit[]> {
  const q = query.trim()
  if (!q) return []
  let result: SearchHit[] = []
  await window.agent.call('conversation.search', { query: q }, (frame) => {
    if (frame.event === 'conversation_search_result' && frame.data) {
      const d = frame.data as { sessions: SearchHit[] }
      result = d.sessions ?? []
    }
  })
  return result
}

export async function deleteConversation(sessionId: string): Promise<void> {
  await window.agent.call(
    'conversation.delete',
    { session_id: sessionId },
    () => {},
  )
}

export type McpServerInfo = {
  name: string
  status: 'connected' | 'failed' | 'gave_up' | 'pending'
  error: string | null
  tools: string[]
}

export type McpStatus = {
  config_path: string
  servers: McpServerInfo[]
}

export async function fetchMcpStatus(): Promise<McpStatus> {
  let result: McpStatus | null = null
  await window.agent.call('mcp.list', {}, (frame) => {
    if (frame.event === 'mcp_list' && frame.data) {
      result = frame.data as McpStatus
    }
  })
  if (!result) throw new Error('mcp.list returned no data')
  return result
}

export type McpStdioConfig = {
  type: 'stdio'
  command: string
  args?: string[]
  env?: Record<string, string>
}

export type McpHttpConfig = {
  type: 'http'
  url: string
  headers?: Record<string, string>
}

export type McpServerConfig = McpStdioConfig | McpHttpConfig

export type McpConfigEntry = {
  name: string
  config: McpServerConfig
}

export async function listMcpConfigs(projectId?: string | null): Promise<{
  config_path: string
  servers: McpConfigEntry[]
}> {
  let out: { config_path: string; servers: McpConfigEntry[] } = {
    config_path: '',
    servers: [],
  }
  const params: Record<string, unknown> = {}
  if (projectId) params.project_id = projectId
  await window.agent.call('mcp.config_list', params, (frame) => {
    if (frame.event === 'mcp_config_list' && frame.data) {
      out = frame.data as { config_path: string; servers: McpConfigEntry[] }
    }
  })
  return out
}

export async function upsertMcpConfig(
  name: string,
  config: McpServerConfig,
  renameFrom?: string,
  projectId?: string | null,
): Promise<void> {
  const params: Record<string, unknown> = { name, config }
  if (renameFrom) params.rename_from = renameFrom
  if (projectId) params.project_id = projectId
  await window.agent.call('mcp.config_upsert', params, () => {})
}

export async function deleteMcpConfig(name: string, projectId?: string | null): Promise<void> {
  const params: Record<string, unknown> = { name }
  if (projectId) params.project_id = projectId
  await window.agent.call('mcp.config_delete', params, () => {})
}

export async function reconnectMcp(name: string): Promise<boolean> {
  let ok = false
  await window.agent.call('mcp.reconnect', { name }, (frame) => {
    if (frame.event === 'mcp_reconnect_result' && frame.data) {
      ok = Boolean((frame.data as { ok?: boolean }).ok)
    }
  })
  return ok
}

export type LoadedAttachmentRef = {
  message_index: number
  attachment_index: number
}

export type LoadedToolCall = {
  tool_use_id: string
  tool_name: string
  input: Record<string, unknown>
  status: 'success' | 'error'
  text: string
}

export type LoadedBlock =
  | { type: 'text'; text: string }
  | { type: 'tools'; tool_use_ids: string[] }

export type LoadedMessage = {
  role: 'user' | 'assistant' | 'system' | 'tool'
  text: string
  message_index: number
  /** Lazy:無 data_url。要 base64 走 loadAttachment(sessionId, ref)。 */
  attachments: Array<{ media_type: string; ref: LoadedAttachmentRef }>
  tool_calls?: LoadedToolCall[]
  blocks?: LoadedBlock[]
  /** Compact 前的舊訊息 — UI 淡化顯示,但仍可 scroll 查看。 */
  compacted?: boolean
  /** 系統訊息 kind('compact-summary' 等)。 */
  kind?: 'compact-summary'
  /** Compact summary card 才有:壓縮前的概略 token 數。 */
  before_tokens?: number
}

export async function loadMessages(sessionId: string): Promise<LoadedMessage[]> {
  let result: LoadedMessage[] = []
  await window.agent.call(
    'conversation.messages',
    { session_id: sessionId },
    (frame) => {
      if (frame.event === 'conversation_messages' && frame.data) {
        const data = frame.data as { messages: LoadedMessage[] }
        result = data.messages ?? []
      }
    },
  )
  return result
}

/** Lazy 拿單張 attachment 的 data_url。 */
export async function loadAttachment(
  sessionId: string,
  messageIndex: number,
  attachmentIndex: number,
): Promise<string> {
  let dataUrl = ''
  await window.agent.call(
    'conversation.attachment',
    {
      session_id: sessionId,
      message_index: messageIndex,
      attachment_index: attachmentIndex,
    },
    (frame) => {
      if (frame.event === 'conversation_attachment' && frame.data) {
        const d = frame.data as { data_url?: string }
        if (typeof d.data_url === 'string') dataUrl = d.data_url
      }
    },
  )
  if (!dataUrl) throw new Error('conversation.attachment returned no data_url')
  return dataUrl
}

export async function regenerateLast(
  sessionId: string,
  onEvent: (ev: SidecarEvent) => void,
): Promise<void> {
  await window.agent.call(
    'conversation.regenerate',
    { session_id: sessionId },
    (frame) => onEvent(frame as unknown as SidecarEvent),
  )
}
