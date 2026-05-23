/**
 * Renderer-side wrapper of window.agent.call。
 *
 * 對外:
 * - createConversation({ provider, model }) → session_id
 * - sendPrompt(session_id, prompt, onEvent) → 等 turn 完成
 * - abort(session_id)
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
   * /export 等想實際寫檔到對話工作目錄的 caller 用這個。 */
  resolved_cwd: string | null
  /** Multi-pane collaboration — session 屬於哪個 collab(NULL = 不在任何 collab)。 */
  collaboration_id: string | null
  /** Session 在 collab 內的 pane 名(@xxx)。NULL = 不是 pane。 */
  pane_name: string | null
}

export async function getSessionWorkspace(sessionId: string): Promise<SessionExt> {
  let ext: SessionExt = {
    session_id: sessionId,
    workspace_dir: null,
    project_id: null,
    resolved_cwd: null,
    collaboration_id: null,
    pane_name: null,
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

// ─── Multi-pane collaboration ─────────────────────────────────────────

export type Collaboration = {
  id: string
  name: string
  workspace_dir: string | null
  project_id: string | null
  budget_usd_cap: number | null
  created_at: number
  updated_at: number
}

export type CollaborationPane = {
  session_id: string
  collaboration_id: string
  pane_name: string
  pane_role: string | null
  pane_position: Record<string, unknown> | null
}

export type CollaborationView = {
  collaboration: Collaboration
  panes: CollaborationPane[]
}

export async function createCollaboration(input: {
  name: string
  workspace_dir?: string | null
  project_id?: string | null
  budget_usd_cap?: number | null
}): Promise<CollaborationView> {
  let out: CollaborationView | null = null
  await window.agent.call('collaboration.create', input as Record<string, unknown>, (frame) => {
    if (frame.event === 'collaboration_created' && frame.data) {
      const d = frame.data as { collaboration: Collaboration; panes: CollaborationPane[] }
      out = { collaboration: d.collaboration, panes: d.panes ?? [] }
    }
  })
  if (!out) throw new Error('collaboration.create returned no collaboration')
  return out
}

export async function listCollaborations(): Promise<CollaborationView[]> {
  let items: CollaborationView[] = []
  await window.agent.call('collaboration.list', {}, (frame) => {
    if (frame.event === 'collaboration_list' && frame.data) {
      const d = frame.data as { items: CollaborationView[] }
      items = d.items ?? []
    }
  })
  return items
}

export async function getCollaboration(
  collaborationId: string,
): Promise<CollaborationView | null> {
  let out: CollaborationView | null = null
  await window.agent.call(
    'collaboration.get',
    { collaboration_id: collaborationId },
    (frame) => {
      if (frame.event === 'collaboration_get' && frame.data) {
        const d = frame.data as { collaboration: Collaboration; panes: CollaborationPane[] }
        out = { collaboration: d.collaboration, panes: d.panes ?? [] }
      }
    },
  )
  return out
}

export async function deleteCollaboration(
  collaborationId: string,
  opts?: { deleteSessions?: boolean },
): Promise<void> {
  await window.agent.call(
    'collaboration.delete',
    {
      collaboration_id: collaborationId,
      delete_sessions: !!opts?.deleteSessions,
    },
    () => {},
  )
}

export async function addPaneToCollaboration(input: {
  collaboration_id: string
  session_id: string
  pane_name: string
  pane_role?: string | null
  pane_position?: Record<string, unknown> | null
}): Promise<void> {
  await window.agent.call(
    'collaboration.add_pane',
    input as Record<string, unknown>,
    () => {},
  )
}

export async function removePaneFromCollaboration(sessionId: string): Promise<void> {
  await window.agent.call(
    'collaboration.remove_pane',
    { session_id: sessionId },
    () => {},
  )
}

export async function updatePanePosition(
  sessionId: string,
  pane_position: Record<string, unknown> | null,
): Promise<void> {
  await window.agent.call(
    'collaboration.update_pane_position',
    { session_id: sessionId, pane_position },
    () => {},
  )
}

export type CollaborationCostPane = {
  session_id: string
  pane_name: string
  pane_role: string | null
  pane_position: Record<string, unknown> | null
  model: string | null
  provider: string | null
  input_tokens: number
  output_tokens: number
  n_turns: number
  n_messages: number
  cost_usd: number
}

export type CollaborationCostSummary = {
  total_panes: number
  input_tokens: number
  output_tokens: number
  total_cost_usd: number
  panes: CollaborationCostPane[]
}

export async function getCollaborationCostSummary(
  collaborationId: string,
): Promise<CollaborationCostSummary | null> {
  let out: CollaborationCostSummary | null = null
  await window.agent.call(
    'collaboration.cost_summary',
    { collaboration_id: collaborationId },
    (frame) => {
      if (frame.event === 'collaboration_cost_summary' && frame.data) {
        out = frame.data as CollaborationCostSummary
      }
    },
  )
  return out
}

// ─── Pane roles ───────────────────────────────────────────────────────

export type RoleSource = 'bundled' | 'user' | 'other' | 'unknown'

export type RoleListItem = {
  name: string
  description: string
  filename: string
  source: RoleSource
  editable: boolean
  source_path: string | null
  default_disabled_tools: string[]
  default_permission_mode: 'ask' | 'act' | null
}

export type Role = RoleListItem & { body: string }

export async function listRoles(): Promise<RoleListItem[]> {
  let items: RoleListItem[] = []
  await window.agent.call('role.list', {}, (frame) => {
    if (frame.event === 'role_list' && frame.data) {
      const d = frame.data as { roles: RoleListItem[] }
      items = d.roles ?? []
    }
  })
  return items
}

export async function getRole(name: string): Promise<Role | null> {
  let r: Role | null = null
  await window.agent.call('role.get', { name }, (frame) => {
    if (frame.event === 'role' && frame.data) {
      r = frame.data as Role
    }
  })
  return r
}

export async function writeRole(input: {
  name: string
  body: string
  description?: string
  default_disabled_tools?: string[]
  default_permission_mode?: 'ask' | 'act' | null
}): Promise<void> {
  await window.agent.call('role.write', input as Record<string, unknown>, () => {})
}

export async function deleteRole(filename: string): Promise<void> {
  await window.agent.call('role.delete', { filename }, () => {})
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
  /** Cowork 桌面 chat 場景是否該顯示。預設 true;false 表此 skill 是 CLI / web 用,
   * 在 Cowork popover 跟 Settings → 技能列表都應隱藏(LLM 仍可載)。 */
  cowork_visible?: boolean
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
 * ALREADY_EXISTS error 時 caller 可加 overwrite=true 再呼一次覆蓋。 */
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

export type BuiltinToolDef = { name: string; description: string }
export type BuiltinToolGroup = { group: string; tools: BuiltinToolDef[] }

/** 列出所有 builtin tools 按組分(Settings → Tools 用)。 */
export async function listBuiltinTools(): Promise<BuiltinToolGroup[]> {
  let out: BuiltinToolGroup[] = []
  await window.agent.call('tools.list_builtin', {}, (frame) => {
    const f = frame as { event?: string; data?: { groups?: BuiltinToolGroup[] } }
    if (f.event === 'tools_builtin' && f.data?.groups) {
      out = f.data.groups
    }
  })
  return out
}

export type Attachment = {
  media_type: string // "image/png" / "image/jpeg" / ...
  data: string // base64-encoded(no data: prefix)
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
    followUpsEnabled?: boolean
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
      follow_ups_enabled: opts?.followUpsEnabled ?? false,
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
 * autoCompactThreshold 應由 caller 從 settings 帶進來,否則 sidecar 用 conv 內的
 * 舊值或預設 0.8,跟 UI 顯示的可能不一致。 */
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
 * Cache 影響:被刪 message 以後的 prefix 變了 → BP3 / BP4 cache 失效,要重寫。 */
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
 * locale 控制摘要語系(zh-TW / zh-CN / ja / en),sidecar 傳給 SDK 摘要 prompt。 */
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

/**
 * 把 tool name + input(+ optional error)翻成自然語言。
 *
 * 兩種觸發場景:
 * - ApprovalBanner「不懂?」按鈕 — 不帶 errorText,解釋 tool 「在做什麼」(一句)
 * - Tool error row「不懂?」按鈕 — 帶 errorText,解釋「為什麼失敗 + 怎麼解」(2-3 句)
 *
 * 用 user 在 Settings 設的「摘要 model」(小、便宜)。沒設或 LLM 失敗時拋 error,
 * caller 顯示 fallback 訊息(e.g. 提示去 Settings 設摘要 model)。
 */
export async function explainToolInput(opts: {
  toolName: string
  toolInput: Record<string, unknown>
  summaryProvider: string | null
  summaryModel: string | null
  locale: string
  /** 帶這個就走 error explain mode(2-3 句,解釋失敗原因 + 建議) */
  errorText?: string
}): Promise<string> {
  let explanation = ''
  let errMessage = ''
  let errCode = ''
  await window.agent.call(
    'tool.explain',
    {
      tool_name: opts.toolName,
      tool_input: opts.toolInput,
      summary_provider: opts.summaryProvider ?? undefined,
      summary_model: opts.summaryModel ?? undefined,
      locale: opts.locale,
      error_text: opts.errorText ?? undefined,
    },
    (frame) => {
      if (frame.event === 'tool_explained') {
        const d = (frame.data ?? {}) as { explanation?: string }
        explanation = d.explanation ?? ''
      } else if (frame.event === 'error') {
        const d = (frame.data ?? {}) as { code?: string; message?: string }
        errCode = d.code ?? 'ERROR'
        errMessage = d.message ?? ''
      }
    },
  )
  if (!explanation) {
    throw new Error(`${errCode}: ${errMessage || 'no explanation'}`)
  }
  return explanation
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

// ─── Cost budget──────────────────────────────────────────

export type SessionBudget = {
  sessionId: string
  budgetUsdCap: number | null // null = unlimited
  currentUsd: number
  exceeded: boolean
}

/** 讀 session 當前 budget + 累積 cost。 */
export async function getSessionBudget(
  sessionId: string,
): Promise<SessionBudget | null> {
  let out: SessionBudget | null = null
  await window.agent.call(
    'conversation.get_budget',
    { session_id: sessionId },
    (frame) => {
      const f = frame as { event?: string; data?: Record<string, unknown> }
      if (f.event !== 'budget' || !f.data) return
      const d = f.data
      out = {
        sessionId: String(d.session_id ?? sessionId),
        budgetUsdCap:
          typeof d.budget_usd_cap === 'number' ? (d.budget_usd_cap as number) : null,
        currentUsd: typeof d.current_usd === 'number' ? (d.current_usd as number) : 0,
        exceeded: Boolean(d.exceeded),
      }
    },
  )
  return out
}

/** 設 / 清 budget cap。傳 null 或 0 等於不限。 */
export async function setSessionBudget(
  sessionId: string,
  budgetUsdCap: number | null,
): Promise<void> {
  await window.agent.call(
    'conversation.set_budget',
    { session_id: sessionId, budget_usd_cap: budgetUsdCap },
    () => {},
  )
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

// ─── Plan Mode──────────────────────────────────────────

/** 開 / 關 Plan Mode — enabled=true 設 pending flag,下次 send 切 ACTIVE。
 * enabled=false 從 active/awaiting → reject_and_exit + 刪 plan_file。 */
export async function setPlanMode(
  sessionId: string,
  enabled: boolean,
): Promise<void> {
  await window.agent.call(
    'conversation.set_plan_mode',
    { session_id: sessionId, enabled },
    () => {},
  )
}

export type PlanApproveResult = {
  follow_up: string
  plan_file_path: string | null
}

/** User 按 Approve。回傳 follow_up 字串,renderer 自己丟下一輪 conversation.send。 */
export async function planApprove(
  sessionId: string,
  followUp?: string,
): Promise<PlanApproveResult> {
  let result: PlanApproveResult = { follow_up: 'Approved. Proceed with the plan.', plan_file_path: null }
  await window.agent.call(
    'conversation.plan_approve',
    { session_id: sessionId, follow_up: followUp },
    (frame) => {
      if (frame.event === 'plan_approved' && frame.data) {
        result = {
          follow_up: (frame.data as { follow_up?: string }).follow_up || result.follow_up,
          plan_file_path: (frame.data as { plan_file_path?: string | null }).plan_file_path ?? null,
        }
      }
    },
  )
  return result
}

/** User 按 Reject(可帶 feedback)。回傳 follow_up 字串給下一輪 send。 */
export async function planReject(
  sessionId: string,
  feedback?: string,
): Promise<{ follow_up: string }> {
  let result = { follow_up: 'Plan rejected. Try a different approach. Don\'t proceed with that plan.' }
  await window.agent.call(
    'conversation.plan_reject',
    { session_id: sessionId, feedback },
    (frame) => {
      if (frame.event === 'plan_rejected' && frame.data) {
        const f = (frame.data as { follow_up?: string }).follow_up
        if (f) result = { follow_up: f }
      }
    },
  )
  return result
}

export type PlanStatusResult = {
  status: 'idle' | 'pending' | 'active' | 'awaiting_approval'
  plan_id: string | null
  plan_markdown: string | null
  plan_file_path: string | null
}

// ─── Attachment staging──────────────────────────────────

export type AttachmentStaged = {
  finalPath: string
  copied: boolean
  inWorkspace: boolean
}

/** Drag-drop 後告訴 sidecar 源檔路徑,sidecar 判斷:
 * - 在 workspace 內 → 不 copy,回原 path
 * - 在外面 → copy 到 <ws>/.orion/uploads/<safe>,回新 path
 * LLM 收到的 prompt prefix 只列 path,不 inline content。 */
export async function prepareAttachmentDrop(
  sessionId: string,
  sourcePath: string,
): Promise<AttachmentStaged> {
  let result: AttachmentStaged = { finalPath: sourcePath, copied: false, inWorkspace: false }
  await window.agent.call(
    'attachment.prepare_drop',
    { session_id: sessionId, source_path: sourcePath },
    (frame) => {
      if (frame.event === 'attachment_staged' && frame.data) {
        const d = frame.data as { final_path?: string; copied?: boolean; in_workspace?: boolean }
        result = {
          finalPath: d.final_path || sourcePath,
          copied: !!d.copied,
          inWorkspace: !!d.in_workspace,
        }
      }
    },
  )
  return result
}

export type WorkspaceFileEntry = {
  relPath: string
  absPath: string
  size: number
}

/** 列 workspace 內檔(給 @file: mention popup),sidecar 端 skip 重的目錄
 * (node_modules / .git / dist 等)、跳 dotfile / dot-dir。回的 list
 * 最多 500 條,truncated=true 表示有更多沒回。 */
export async function listWorkspaceFiles(
  sessionId: string,
  max?: number,
): Promise<{ workspaceDir: string | null; files: WorkspaceFileEntry[]; truncated: boolean }> {
  let result = { workspaceDir: null as string | null, files: [] as WorkspaceFileEntry[], truncated: false }
  await window.agent.call(
    'workspace.list_files',
    max ? { session_id: sessionId, max } : { session_id: sessionId },
    (frame) => {
      if (frame.event === 'workspace_files' && frame.data) {
        const d = frame.data as {
          workspace_dir?: string | null
          files?: Array<{ rel_path: string; abs_path: string; size: number }>
          truncated?: boolean
        }
        result = {
          workspaceDir: d.workspace_dir ?? null,
          files: (d.files ?? []).map((f) => ({
            relPath: f.rel_path,
            absPath: f.abs_path,
            size: f.size,
          })),
          truncated: !!d.truncated,
        }
      }
    },
  )
  return result
}

/** File picker 場景(沒 source path 只有 content)— 一律寫進 uploads dir。 */
export async function saveUploadedAttachment(
  sessionId: string,
  filename: string,
  contentB64: string,
): Promise<AttachmentStaged> {
  let result: AttachmentStaged = { finalPath: '', copied: true, inWorkspace: false }
  await window.agent.call(
    'attachment.save_uploaded',
    { session_id: sessionId, filename, content_b64: contentB64 },
    (frame) => {
      if (frame.event === 'attachment_staged' && frame.data) {
        const d = frame.data as { final_path?: string; copied?: boolean; in_workspace?: boolean }
        result = {
          finalPath: d.final_path || '',
          copied: !!d.copied,
          inWorkspace: !!d.in_workspace,
        }
      }
    },
  )
  return result
}

/** Renderer mount 時呼 — 從 sidecar 查 session 當前 plan mode 狀態,re-hydrate UI。 */
export async function planStatus(sessionId: string): Promise<PlanStatusResult> {
  let result: PlanStatusResult = { status: 'idle', plan_id: null, plan_markdown: null, plan_file_path: null }
  await window.agent.call(
    'conversation.plan_status',
    { session_id: sessionId },
    (frame) => {
      if (frame.event === 'plan_status' && frame.data) {
        const d = frame.data as Partial<PlanStatusResult>
        result = {
          status: d.status || 'idle',
          plan_id: d.plan_id ?? null,
          plan_markdown: d.plan_markdown ?? null,
          plan_file_path: d.plan_file_path ?? null,
        }
      }
    },
  )
  return result
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
  via_proxy?: boolean
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
          via_proxy: !!p.via_proxy,
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
 * durationSeconds 由前端錄音時量;後端用 catalog pricing × duration 算 cost。 */
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

// ─── TTS──────────────────────────────────────────────────

export type TtsResult = {
  audioBase64: string
  mimeType: string
  charCount: number
  costUsd: number
  cacheHit: boolean
}

/** 呼 sidecar 把 text → audio。Web Speech API 走另一條 path,不經這 RPC。 */
export async function synthesizeSpeech(opts: {
  text: string
  provider: 'openai'
  model: string
  voice: string
  speed: number
}): Promise<TtsResult> {
  let result: TtsResult = {
    audioBase64: '',
    mimeType: 'audio/mpeg',
    charCount: 0,
    costUsd: 0,
    cacheHit: false,
  }
  let errMsg: string | null = null
  await window.agent.call(
    'tts.synthesize',
    {
      provider: opts.provider,
      model: opts.model,
      voice: opts.voice,
      speed: opts.speed,
      text: opts.text,
      format: 'mp3',
    },
    (frame) => {
      const f = frame as {
        event?: string
        data?: Record<string, unknown>
        error?: { message?: string }
      }
      if (f.error?.message) errMsg = f.error.message
      else if (f.event === 'error' && typeof f.data?.message === 'string')
        errMsg = f.data.message as string
      else if (f.event === 'tts_synthesized' && f.data) {
        const d = f.data
        result = {
          audioBase64: typeof d.audio_base64 === 'string' ? d.audio_base64 : '',
          mimeType: typeof d.mime_type === 'string' ? d.mime_type : 'audio/mpeg',
          charCount: typeof d.char_count === 'number' ? d.char_count : 0,
          costUsd: typeof d.cost_usd === 'number' ? d.cost_usd : 0,
          cacheHit: Boolean(d.cache_hit),
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
    /** True = optimistic configured(走 proxy,沒驗證 token/upstream)。 */
    via_proxy?: boolean
    /** Ollama 之類動態 provider — 不靠 catalog,要 caller 跑 ollama.list_models 拿 model list */
    dynamic?: boolean
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

// ─── Ollama(local model)─────────────────────────────────────────

export type OllamaModelInfo = {
  name: string
  size?: number
  modified_at?: string
  digest?: string
  details?: {
    parameter_size?: string
    quantization_level?: string
    family?: string
  }
}

export type OllamaListResult = {
  models: OllamaModelInfo[]
  base_url: string
}

/** 從 user 本機 Ollama 抓已 pull 的 model 列表(GET /api/tags)。
 * 失敗(Ollama 沒開 / 連不上)會 throw — caller 自己處理 banner UI。 */
export async function listOllamaModels(baseUrl?: string): Promise<OllamaListResult> {
  let result: OllamaListResult | null = null
  let errMsg: string | null = null
  await window.agent.call(
    'ollama.list_models',
    baseUrl ? { base_url: baseUrl } : {},
    (frame) => {
      if (frame.event === 'ollama_models' && frame.data) {
        result = frame.data as OllamaListResult
      } else if (frame.event === 'error' && frame.data) {
        errMsg = (frame.data as { message?: string }).message || 'Ollama unreachable'
      }
    },
  )
  if (errMsg) throw new Error(errMsg)
  if (!result) throw new Error('ollama.list_models returned no data')
  return result
}

export type OllamaHealth = {
  ok: boolean
  version?: string
  error?: string
  base_url: string
}

/** Ping `/api/version` 看 Ollama daemon 是否在跑。失敗回 {ok: false, error}。 */
export async function checkOllamaHealth(baseUrl?: string): Promise<OllamaHealth> {
  let result: OllamaHealth = { ok: false, base_url: baseUrl || '' }
  await window.agent.call(
    'ollama.health',
    baseUrl ? { base_url: baseUrl } : {},
    (frame) => {
      if (frame.event === 'ollama_health' && frame.data) {
        result = frame.data as OllamaHealth
      }
    },
  )
  return result
}

export type SessionSummary = {
  session_id: string
  provider: string
  model: string
  title: string | null
  created_at: number
  n_messages: number
  starred?: boolean
  scheduled_by?: { schedule_id: string; schedule_name: string } | null
  forked_from_session_id?: string | null
  forked_from_message_index?: number | null
}

export async function renameConversation(
  sessionId: string, title: string,
): Promise<void> {
  await window.agent.call(
    'conversation.rename',
    { session_id: sessionId, title },
    () => {},
  )
}

export async function setSessionStarred(
  sessionId: string, starred: boolean,
): Promise<void> {
  await window.agent.call(
    'conversation.set_starred',
    { session_id: sessionId, starred },
    () => {},
  )
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

export type BulkDeleteStats = {
  requested: number
  deleted: number
  descendantsDeleted: number
  totalTargets: number
}

/** Bulk delete 多個 session — 每個都 cascade fork 子孫。回統計。 */
export async function deleteConversations(
  sessionIds: string[],
): Promise<BulkDeleteStats> {
  let stats: BulkDeleteStats = {
    requested: sessionIds.length,
    deleted: 0,
    descendantsDeleted: 0,
    totalTargets: 0,
  }
  await window.agent.call(
    'conversation.delete_many',
    { session_ids: sessionIds },
    (frame) => {
      const f = frame as { event?: string; data?: Record<string, unknown> }
      if (f.event === 'conversation_deleted_many' && f.data) {
        const d = f.data
        stats = {
          requested: typeof d.requested === 'number' ? d.requested : sessionIds.length,
          deleted: typeof d.deleted === 'number' ? d.deleted : 0,
          descendantsDeleted: typeof d.descendants_deleted === 'number' ? d.descendants_deleted : 0,
          totalTargets: typeof d.total_targets === 'number' ? d.total_targets : 0,
        }
      }
    },
  )
  return stats
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

/** 算該 session 有幾個 fork 子孫(遞迴往下,不含 self)— delete confirm 顯警告用。 */
export async function countForkDescendants(sessionId: string): Promise<number> {
  let count = 0
  await window.agent.call(
    'conversation.count_fork_descendants',
    { session_id: sessionId },
    (frame) => {
      const f = frame as { event?: string; data?: Record<string, unknown> }
      if (f.event === 'fork_descendants_count' && f.data) {
        count = typeof f.data.count === 'number' ? f.data.count : 0
      }
    },
  )
  return count
}

/**
 * 從 source session 第 N 筆訊息(inclusive)分叉出新 session — 原 session 完全不動。
 * 新 session messages [0..upToMessageIndex] 來自 source,workspace / project 繼承,
 * budget / plan 不繼承。回傳新 session_id。
 */
export async function forkConversation(
  sourceSessionId: string,
  upToMessageIndex: number,
  title?: string,
): Promise<string> {
  let newSid: string | null = null
  await window.agent.call(
    'conversation.fork',
    {
      source_session_id: sourceSessionId,
      up_to_message_index: upToMessageIndex,
      ...(title ? { title } : {}),
    },
    (frame) => {
      const f = frame as { event?: string; data?: Record<string, unknown> }
      if (f.event === 'conversation_forked' && f.data) {
        newSid = String(f.data.session_id ?? '')
      }
    },
  )
  if (!newSid) throw new Error('conversation.fork returned no session_id')
  return newSid
}

// ─── Schedule(對話排程)─────────────────────────────────────────────
export type ScheduleScope = 'user' | 'project'
export type ScheduleTriggerType = 'skill' | 'prompt'
export type ScheduleStatus = 'ok' | 'error' | 'skipped'

export type Schedule = {
  id: string
  name: string
  cron_expr: string
  trigger_type: ScheduleTriggerType
  payload: string
  scope: ScheduleScope
  project_id: string | null
  enabled: boolean
  last_run_at: number | null
  next_run_at: number | null
  last_run_session_id: string | null
  last_run_status: ScheduleStatus | null
  last_error: string | null
  model_provider: string | null
  model: string | null
  workspace_dir: string | null
  created_at: number
  updated_at: number
  /** Loop:有值 = 綁定此 session,每次 fire 送回該對話;null = 排程模式(開新 session) */
  target_session_id: string | null
  /** sidecar 標的便利欄,'loop' or 'schedule'(從 target_session_id 推導) */
  kind: 'loop' | 'schedule'
}

export async function listSchedules(opts?: {
  scope?: 'user' | 'project' | 'all'
  projectId?: string | null
}): Promise<Schedule[]> {
  const params: Record<string, unknown> = {}
  if (opts?.scope) params.scope = opts.scope
  if (opts?.projectId) params.project_id = opts.projectId
  let items: Schedule[] = []
  await window.agent.call('schedule.list', params, (frame) => {
    if (frame.event === 'schedule_list' && frame.data) {
      items = (frame.data as { schedules: Schedule[] }).schedules ?? []
    }
  })
  return items
}

export async function getSchedule(id: string): Promise<Schedule | null> {
  let s: Schedule | null = null
  await window.agent.call('schedule.get', { id }, (frame) => {
    if (frame.event === 'schedule' && frame.data) {
      s = (frame.data as { schedule: Schedule | null }).schedule
    }
  })
  return s
}

export type WriteScheduleInput = {
  id?: string | null
  name: string
  cron_expr: string
  trigger_type: ScheduleTriggerType
  payload: string
  scope: ScheduleScope
  project_id?: string | null
  enabled: boolean
  model_provider?: string | null
  model?: string | null
  workspace_dir?: string | null
  /** Loop:有值 = 綁定此 session,fire 送回該對話 */
  target_session_id?: string | null
}

export async function writeSchedule(input: WriteScheduleInput): Promise<Schedule | null> {
  let s: Schedule | null = null
  await window.agent.call('schedule.write', input as Record<string, unknown>, (frame) => {
    if (frame.event === 'schedule_written' && frame.data) {
      s = (frame.data as { schedule: Schedule }).schedule
    }
  })
  return s
}

export async function deleteSchedule(id: string): Promise<void> {
  await window.agent.call('schedule.delete', { id }, () => {})
}

export async function runScheduleNow(id: string): Promise<void> {
  await window.agent.call('schedule.run_now', { id }, () => {})
}

// ─── Backup / Restore ─────────────────────────────────────────────────────

export type BackupPreview = {
  db_bytes: number
  blobs_bytes: number
  blobs_count: number
  other_bytes: number
  total_bytes: number
}

export type BackupManifest = {
  schema_version: number
  exported_at: number
  include_blobs: boolean
  data_dir: string
  file_count: number
  has_db: boolean
}

export async function backupPreview(includeBlobs: boolean): Promise<BackupPreview> {
  let result: BackupPreview = {
    db_bytes: 0,
    blobs_bytes: 0,
    blobs_count: 0,
    other_bytes: 0,
    total_bytes: 0,
  }
  await window.agent.call(
    'backup.preview',
    { include_blobs: includeBlobs },
    (frame) => {
      if (frame.event === 'backup.preview' && frame.data) {
        result = frame.data as BackupPreview
      }
    },
  )
  return result
}

export async function backupExport(
  targetPath: string,
  includeBlobs: boolean,
): Promise<{ path: string; total_bytes: number; manifest: BackupManifest }> {
  let result: { path: string; total_bytes: number; manifest: BackupManifest } | null = null
  await window.agent.call(
    'backup.export',
    { target_path: targetPath, include_blobs: includeBlobs },
    (frame) => {
      if (frame.event === 'backup.exported' && frame.data) {
        result = frame.data as {
          path: string
          total_bytes: number
          manifest: BackupManifest
        }
      }
    },
  )
  if (!result) throw new Error('backup.export did not return final frame')
  return result
}

export async function backupInspect(
  sourcePath: string,
): Promise<{ manifest: BackupManifest; zip_size: number }> {
  let result: { manifest: BackupManifest; zip_size: number } | null = null
  await window.agent.call(
    'backup.inspect',
    { source_path: sourcePath },
    (frame) => {
      if (frame.event === 'backup.inspected' && frame.data) {
        result = frame.data as { manifest: BackupManifest; zip_size: number }
      }
    },
  )
  if (!result) throw new Error('backup.inspect did not return final frame')
  return result
}

export async function backupRestore(sourcePath: string): Promise<{ moved_to: string }> {
  let result: { moved_to: string } | null = null
  await window.agent.call(
    'backup.restore',
    { source_path: sourcePath },
    (frame) => {
      if (frame.event === 'backup.restored' && frame.data) {
        result = frame.data as { moved_to: string }
      }
    },
  )
  if (!result) throw new Error('backup.restore did not return final frame')
  return result
}
