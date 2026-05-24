import { create } from 'zustand'
import { apiFetch } from '../api/client'
import { setPreferredModel, type ModelChoice } from '../lib/preferredModel'
import type { SessionSummary } from '../types/events'

/**
 * Session 清單 + 當前選取 + draft 狀態的單一真實來源。
 *
 * 取代舊的 useSessions hook 與 App.tsx 的 orchestration。後續 phase(title /
 * star / fork)可直接呼 store action 改 sessions,不必把 callback 一層層往上傳。
 *
 * Draft 模式:使用者按 New chat 但還沒送第一則訊息 — 此時 currentSid=null、
 * draft=挑選的 model,不打 backend create;送出第一則訊息時 commitDraft() 才真正建。
 */

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

async function createSession(choice?: ModelChoice): Promise<SessionSummary> {
  return apiFetch<SessionSummary>('/sessions', {
    method: 'POST',
    body: choice
      ? { provider: choice.provider, model: choice.model }
      : undefined,
  })
}

interface SessionState {
  sessions: SessionSummary[]
  loading: boolean
  error: string | null
  currentSid: string | null
  draft: ModelChoice | null

  refresh: () => Promise<void>
  selectSession: (sid: string) => void
  startDraft: (choice: ModelChoice | null) => void
  setDraft: (choice: ModelChoice | null) => void
  commitDraft: () => Promise<string | null>
  changeModel: (choice: ModelChoice) => Promise<void>
  remove: (sid: string) => Promise<void>
  rename: (sid: string, title: string) => Promise<void>
  toggleStar: (sid: string) => Promise<void>
  applyTitleUpdate: (sid: string, title: string) => void
  forkSession: (sid: string, upTo?: number) => Promise<string | null>
  compact: (sid: string) => Promise<void>
  reset: () => void
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  loading: false,
  error: null,
  currentSid: null,
  draft: null,

  refresh: async () => {
    set({ loading: true, error: null })
    try {
      const list = (await apiFetch<SessionSummary[]>('/sessions')) || []
      set((st) => {
        const stillExists =
          st.currentSid != null &&
          list.some((s) => s.session_id === st.currentSid)
        // draft 模式不自動跳 session;否則 currentSid 失效就選第一個
        const currentSid =
          st.draft || stillExists
            ? st.currentSid
            : (list[0]?.session_id ?? null)
        return { sessions: list, currentSid }
      })
    } catch (e) {
      set({ error: errMsg(e) })
    } finally {
      set({ loading: false })
    }
  },

  selectSession: (sid) => set({ draft: null, currentSid: sid }),

  startDraft: (choice) => set({ currentSid: null, draft: choice }),

  setDraft: (choice) => set({ draft: choice }),

  commitDraft: async () => {
    const choice = get().draft ?? undefined
    try {
      const s = await createSession(choice)
      setPreferredModel({ provider: s.provider, model: s.model })
      set((st) => ({
        sessions: [
          s,
          ...st.sessions.filter((p) => p.session_id !== s.session_id),
        ],
        draft: null,
        currentSid: s.session_id,
      }))
      return s.session_id
    } catch (e) {
      set({ error: errMsg(e) })
      return null
    }
  },

  changeModel: async (choice) => {
    const { draft, currentSid, sessions } = get()
    if (draft !== null) {
      set({ draft: choice })
      return
    }
    // model picker 只在 empty session 出現 — 把上一個空 session 刪掉
    const cur = sessions.find((s) => s.session_id === currentSid)
    if (currentSid && cur && cur.n_messages === 0) {
      await get().remove(currentSid)
    }
    try {
      const s = await createSession(choice)
      setPreferredModel({ provider: s.provider, model: s.model })
      set((st) => ({
        sessions: [
          s,
          ...st.sessions.filter((p) => p.session_id !== s.session_id),
        ],
        currentSid: s.session_id,
      }))
    } catch (e) {
      set({ error: errMsg(e) })
    }
  },

  remove: async (sid) => {
    // Optimistic remove — UI 立即更新,失敗 rollback
    let snapshot: SessionSummary[] = []
    set((st) => {
      snapshot = st.sessions
      const sessions = st.sessions.filter((s) => s.session_id !== sid)
      const currentSid =
        st.currentSid === sid
          ? st.draft
            ? null
            : (sessions[0]?.session_id ?? null)
          : st.currentSid
      return { sessions, currentSid }
    })
    try {
      await apiFetch(`/sessions/${sid}`, { method: 'DELETE' })
    } catch (e) {
      set({ sessions: snapshot, error: errMsg(e) })
    }
  },

  rename: async (sid, title) => {
    try {
      const updated = await apiFetch<SessionSummary>(`/sessions/${sid}`, {
        method: 'PATCH',
        body: { title },
      })
      set((st) => ({
        sessions: st.sessions.map((s) =>
          s.session_id === sid ? { ...s, title: updated.title ?? title } : s,
        ),
      }))
    } catch (e) {
      set({ error: errMsg(e) })
    }
  },

  toggleStar: async (sid) => {
    const cur = get().sessions.find((s) => s.session_id === sid)
    const next = !cur?.starred
    // optimistic
    set((st) => ({
      sessions: st.sessions.map((s) =>
        s.session_id === sid ? { ...s, starred: next } : s,
      ),
    }))
    try {
      await apiFetch(`/sessions/${sid}`, {
        method: 'PATCH',
        body: { starred: next },
      })
    } catch (e) {
      set((st) => ({
        sessions: st.sessions.map((s) =>
          s.session_id === sid ? { ...s, starred: !next } : s,
        ),
        error: errMsg(e),
      }))
    }
  },

  applyTitleUpdate: (sid, title) =>
    set((st) => ({
      sessions: st.sessions.map((s) =>
        s.session_id === sid ? { ...s, title } : s,
      ),
    })),

  forkSession: async (sid, upTo) => {
    try {
      const created = await apiFetch<SessionSummary>(`/sessions/${sid}/fork`, {
        method: 'POST',
        body: upTo != null ? { up_to_message_index: upTo } : {},
      })
      set((st) => ({
        sessions: [
          created,
          ...st.sessions.filter((s) => s.session_id !== created.session_id),
        ],
        currentSid: created.session_id,
        draft: null,
      }))
      return created.session_id
    } catch (e) {
      set({ error: errMsg(e) })
      return null
    }
  },

  compact: async (sid) => {
    try {
      await apiFetch(`/sessions/${sid}/compact?force=true`, { method: 'POST' })
    } catch (e) {
      set({ error: errMsg(e) })
    }
  },

  reset: () =>
    set({ sessions: [], currentSid: null, draft: null, error: null }),
}))
