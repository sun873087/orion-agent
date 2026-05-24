import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiFetchMock } = vi.hoisted(() => ({ apiFetchMock: vi.fn() }))
vi.mock('../api/client', () => ({ apiFetch: apiFetchMock }))

import { useUiStore } from './uiStore'

beforeEach(() => {
  apiFetchMock.mockReset()
  apiFetchMock.mockResolvedValue({})
  localStorage.clear()
  useUiStore.setState({
    locale: 'en',
    sidebarCollapsed: false,
    settingsOpen: false,
  })
})

describe('uiStore', () => {
  it('setLocale updates state, persists localStorage, and syncs backend', () => {
    useUiStore.getState().setLocale('ja')
    expect(useUiStore.getState().locale).toBe('ja')
    expect(localStorage.getItem('orion.locale')).toBe('ja')
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/me/settings/locale',
      expect.objectContaining({ method: 'PUT', body: { value: 'ja' } }),
    )
  })

  it('toggleSidebar flips and persists', () => {
    useUiStore.getState().toggleSidebar()
    expect(useUiStore.getState().sidebarCollapsed).toBe(true)
    expect(localStorage.getItem('orion.sidebarCollapsed')).toBe('1')
    useUiStore.getState().toggleSidebar()
    expect(useUiStore.getState().sidebarCollapsed).toBe(false)
    expect(localStorage.getItem('orion.sidebarCollapsed')).toBe('0')
  })

  it('open/closeSettings toggles settingsOpen', () => {
    useUiStore.getState().openSettings()
    expect(useUiStore.getState().settingsOpen).toBe(true)
    useUiStore.getState().closeSettings()
    expect(useUiStore.getState().settingsOpen).toBe(false)
  })

  it('hydrateLocaleFromBackend applies a valid remote locale', async () => {
    apiFetchMock.mockResolvedValueOnce({ locale: 'zh-CN' })
    await useUiStore.getState().hydrateLocaleFromBackend()
    expect(useUiStore.getState().locale).toBe('zh-CN')
  })

  it('hydrateLocaleFromBackend ignores invalid remote values', async () => {
    apiFetchMock.mockResolvedValueOnce({ locale: 'klingon' })
    await useUiStore.getState().hydrateLocaleFromBackend()
    expect(useUiStore.getState().locale).toBe('en')
  })
})
