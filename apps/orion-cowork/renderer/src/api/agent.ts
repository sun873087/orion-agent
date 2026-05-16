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
  | { event: string; data?: unknown; final?: boolean }

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
}

export async function getSessionWorkspace(sessionId: string): Promise<SessionExt> {
  let ext: SessionExt = { session_id: sessionId, workspace_dir: null, project_id: null }
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

export async function listMemories(): Promise<{
  memory_dir: string
  memories: MemoryListItem[]
}> {
  let out: { memory_dir: string; memories: MemoryListItem[] } = {
    memory_dir: '',
    memories: [],
  }
  await window.agent.call('memory.list', {}, (frame) => {
    if (frame.event === 'memory_list' && frame.data) {
      out = frame.data as { memory_dir: string; memories: MemoryListItem[] }
    }
  })
  return out
}

export async function getMemory(filename: string): Promise<Memory | null> {
  let m: Memory | null = null
  await window.agent.call('memory.get', { filename }, (frame) => {
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

export async function deleteMemory(filename: string): Promise<void> {
  await window.agent.call('memory.delete', { filename }, () => {})
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

export async function listSkills(): Promise<{
  user_skills_dir: string
  skills: SkillListItem[]
}> {
  let out: { user_skills_dir: string; skills: SkillListItem[] } = {
    user_skills_dir: '',
    skills: [],
  }
  await window.agent.call('skill.list', {}, (frame) => {
    if (frame.event === 'skill_list' && frame.data) {
      out = frame.data as { user_skills_dir: string; skills: SkillListItem[] }
    }
  })
  return out
}

export async function getSkill(name: string): Promise<Skill | null> {
  let s: Skill | null = null
  await window.agent.call('skill.get', { name }, (frame) => {
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
}): Promise<void> {
  await window.agent.call('skill.write', input as Record<string, unknown>, () => {})
}

export async function deleteSkill(filename: string): Promise<void> {
  await window.agent.call('skill.delete', { filename }, () => {})
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
): Promise<void> {
  await window.agent.call(
    'conversation.send',
    {
      session_id: sessionId,
      prompt,
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

export async function abort(sessionId: string): Promise<void> {
  await window.agent.call('conversation.abort', { session_id: sessionId }, () => {})
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

export async function listMcpConfigs(): Promise<{
  config_path: string
  servers: McpConfigEntry[]
}> {
  let out: { config_path: string; servers: McpConfigEntry[] } = {
    config_path: '',
    servers: [],
  }
  await window.agent.call('mcp.config_list', {}, (frame) => {
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
): Promise<void> {
  const params: Record<string, unknown> = { name, config }
  if (renameFrom) params.rename_from = renameFrom
  await window.agent.call('mcp.config_upsert', params, () => {})
}

export async function deleteMcpConfig(name: string): Promise<void> {
  await window.agent.call('mcp.config_delete', { name }, () => {})
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

export type LoadedMessage = {
  role: 'user' | 'assistant' | 'system' | 'tool'
  text: string
  message_index: number
  /** Lazy:無 data_url。要 base64 走 loadAttachment(sessionId, ref)。 */
  attachments: Array<{ media_type: string; ref: LoadedAttachmentRef }>
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
