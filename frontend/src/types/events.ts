// 對應 backend `api/event_schema.py`(Phase 6)。
// 任何 backend schema 改動,本檔同步更新。

// ─── Client → Server ────────────────────────────────────────────────────────

export interface UserMessageEvent {
  type: 'user_message'
  content: string
}

export interface PermissionDecisionEvent {
  type: 'permission_decision'
  request_id: string
  decision: 'allow' | 'always_allow' | 'deny' | 'always_deny'
}

export interface AbortEvent {
  type: 'abort'
}

export type ClientEvent =
  | UserMessageEvent
  | PermissionDecisionEvent
  | AbortEvent

// ─── Server → Client ────────────────────────────────────────────────────────

export interface UserTextEvent {
  type: 'user_text'
  text: string
}

export interface HistoryReplayDoneEvent {
  type: 'history_replay_done'
}

export interface AssistantTextEvent {
  type: 'assistant_text'
  text: string
}

export interface AssistantThinkingEvent {
  type: 'assistant_thinking'
  text: string
}

export interface ToolUseEvent {
  type: 'tool_use'
  tool_use_id: string
  tool_name: string
  input: Record<string, unknown>
}

export interface ToolResultEvent {
  type: 'tool_result'
  tool_use_id: string
  tool_name: string
  content: string
  is_error?: boolean
}

export interface PermissionAskEvent {
  type: 'permission_ask'
  request_id: string
  tool_name: string
  input: Record<string, unknown>
  timeout_seconds?: number
}

export interface TurnCompleteEvent {
  type: 'turn_complete'
  stop_reason: string
  input_tokens: number
  output_tokens: number
}

export interface TerminalEvent {
  type: 'terminal'
  reason: string
  total_turns: number
}

export interface ServerErrorEvent {
  type: 'error'
  message: string
}

export type ServerEvent =
  | UserTextEvent
  | HistoryReplayDoneEvent
  | AssistantTextEvent
  | AssistantThinkingEvent
  | ToolUseEvent
  | ToolResultEvent
  | PermissionAskEvent
  | TurnCompleteEvent
  | TerminalEvent
  | ServerErrorEvent

// ─── REST 型別 ──────────────────────────────────────────────────────────────

export interface SessionSummary {
  session_id: string
  user_id: string
  n_messages: number
  n_turns: number
  provider: string
  model: string
}

export interface ModelEntry {
  id: string
  label: string
}

export interface ProviderEntry {
  id: string
  label: string
  available: boolean
  models: ModelEntry[]
}

export interface ModelCatalog {
  providers: ProviderEntry[]
  default: { provider: string; model: string }
}

export interface CostSummary {
  session_id?: string
  total_cost_usd: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_creation_tokens: number
  reasoning_tokens: number
  cache_hit_ratio?: number
}

export interface UploadSummary {
  upload_id: string
  filename: string
  size: number
}

export interface CustomInstructionsResponse {
  user_level: string | null
  conversation_level: string | null
}

export interface SettingValue {
  key: string
  value: unknown
  version: number
}
