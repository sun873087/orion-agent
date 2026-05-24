import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionSummary } from '../types/events'

const { apiFetchMock } = vi.hoisted(() => ({ apiFetchMock: vi.fn() }))
vi.mock('../api/client', () => ({ apiFetch: apiFetchMock }))

import { useSessionStore } from './sessionStore'

function mk(id: string, nMessages = 1): SessionSummary {
  return {
    session_id: id,
    n_messages: nMessages,
    n_turns: 0,
    provider: 'anthropic',
    model: 'claude-sonnet-4-6',
  } as SessionSummary
}

beforeEach(() => {
  apiFetchMock.mockReset()
  localStorage.clear()
  useSessionStore.setState({
    sessions: [],
    loading: false,
    error: null,
    currentSid: null,
    draft: null,
  })
})

describe('sessionStore.refresh', () => {
  it('auto-selects the first session when none selected', async () => {
    apiFetchMock.mockResolvedValueOnce([mk('a'), mk('b')])
    await useSessionStore.getState().refresh()
    const s = useSessionStore.getState()
    expect(s.sessions).toHaveLength(2)
    expect(s.currentSid).toBe('a')
  })

  it('keeps currentSid null while a draft is active', async () => {
    useSessionStore.setState({ draft: { provider: 'p', model: 'm' } })
    apiFetchMock.mockResolvedValueOnce([mk('a')])
    await useSessionStore.getState().refresh()
    expect(useSessionStore.getState().currentSid).toBeNull()
  })

  it('corrects a stale currentSid that no longer exists', async () => {
    useSessionStore.setState({ currentSid: 'gone' })
    apiFetchMock.mockResolvedValueOnce([mk('a')])
    await useSessionStore.getState().refresh()
    expect(useSessionStore.getState().currentSid).toBe('a')
  })

  it('records error on failure without throwing', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('boom'))
    await useSessionStore.getState().refresh()
    expect(useSessionStore.getState().error).toBe('boom')
    expect(useSessionStore.getState().loading).toBe(false)
  })
})

describe('sessionStore.commitDraft', () => {
  it('creates the session, clears draft, prepends and selects it', async () => {
    useSessionStore.setState({ draft: { provider: 'p', model: 'm' } })
    apiFetchMock.mockResolvedValueOnce(mk('new', 0))
    const sid = await useSessionStore.getState().commitDraft()
    const s = useSessionStore.getState()
    expect(sid).toBe('new')
    expect(s.draft).toBeNull()
    expect(s.currentSid).toBe('new')
    expect(s.sessions[0]?.session_id).toBe('new')
  })
})

describe('sessionStore.remove', () => {
  it('optimistically removes and reselects the next session', async () => {
    useSessionStore.setState({ sessions: [mk('a'), mk('b')], currentSid: 'a' })
    apiFetchMock.mockResolvedValueOnce(undefined)
    await useSessionStore.getState().remove('a')
    const s = useSessionStore.getState()
    expect(s.sessions.map((x) => x.session_id)).toEqual(['b'])
    expect(s.currentSid).toBe('b')
  })

  it('rolls back on delete failure', async () => {
    useSessionStore.setState({ sessions: [mk('a'), mk('b')], currentSid: 'a' })
    apiFetchMock.mockRejectedValueOnce(new Error('nope'))
    await useSessionStore.getState().remove('a')
    const s = useSessionStore.getState()
    expect(s.sessions).toHaveLength(2)
    expect(s.error).toBe('nope')
  })
})

describe('sessionStore.rename / star / title', () => {
  it('rename updates the session title', async () => {
    useSessionStore.setState({ sessions: [mk('a')] })
    apiFetchMock.mockResolvedValueOnce({ ...mk('a'), title: 'Renamed' })
    await useSessionStore.getState().rename('a', 'Renamed')
    expect(useSessionStore.getState().sessions[0]?.title).toBe('Renamed')
  })

  it('toggleStar optimistically flips and persists', async () => {
    useSessionStore.setState({ sessions: [mk('a')] })
    apiFetchMock.mockResolvedValueOnce(undefined)
    await useSessionStore.getState().toggleStar('a')
    expect(useSessionStore.getState().sessions[0]?.starred).toBe(true)
  })

  it('toggleStar rolls back on failure', async () => {
    useSessionStore.setState({ sessions: [{ ...mk('a'), starred: true }] })
    apiFetchMock.mockRejectedValueOnce(new Error('x'))
    await useSessionStore.getState().toggleStar('a')
    expect(useSessionStore.getState().sessions[0]?.starred).toBe(true)
  })

  it('applyTitleUpdate sets the title (WS-driven)', () => {
    useSessionStore.setState({ sessions: [mk('a')] })
    useSessionStore.getState().applyTitleUpdate('a', 'Auto Title')
    expect(useSessionStore.getState().sessions[0]?.title).toBe('Auto Title')
  })

  it('forkSession prepends and selects the new session', async () => {
    useSessionStore.setState({ sessions: [mk('a')], currentSid: 'a' })
    apiFetchMock.mockResolvedValueOnce(mk('forked', 2))
    const sid = await useSessionStore.getState().forkSession('a')
    expect(sid).toBe('forked')
    const s = useSessionStore.getState()
    expect(s.currentSid).toBe('forked')
    expect(s.sessions[0]?.session_id).toBe('forked')
  })
})

describe('sessionStore.changeModel', () => {
  it('updates draft in place when a draft is active', async () => {
    useSessionStore.setState({ draft: { provider: 'p', model: 'm' } })
    await useSessionStore
      .getState()
      .changeModel({ provider: 'p2', model: 'm2' })
    expect(useSessionStore.getState().draft).toEqual({
      provider: 'p2',
      model: 'm2',
    })
    expect(apiFetchMock).not.toHaveBeenCalled()
  })

  it('drops the empty current session then creates a new one', async () => {
    useSessionStore.setState({
      sessions: [mk('empty', 0)],
      currentSid: 'empty',
    })
    apiFetchMock
      .mockResolvedValueOnce(undefined) // DELETE empty
      .mockResolvedValueOnce(mk('new2', 0)) // POST create
    await useSessionStore
      .getState()
      .changeModel({ provider: 'p2', model: 'm2' })
    const s = useSessionStore.getState()
    expect(s.currentSid).toBe('new2')
    expect(s.sessions.map((x) => x.session_id)).not.toContain('empty')
  })
})
