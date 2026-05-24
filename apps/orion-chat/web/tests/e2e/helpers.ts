import { type APIRequestContext, type Page, expect } from '@playwright/test'

/**
 * 註冊 + 登入一個唯一 user,把 token 種進 localStorage,讓接下來的 page.goto('/')
 * 直接進入已登入的 app。
 *
 * 用唯一 username 避免同一 run 內(共用 DB)跨 test 撞名。auth 走 vite proxy →
 * chat-api(MockProvider)。
 */
export async function loginFreshUser(
  page: Page,
  request: APIRequestContext,
): Promise<{ username: string; token: string }> {
  const username = `pw_${Date.now()}_${Math.floor(Math.random() * 1e6)}`
  const password = 'passw0rd'
  await request.post('/auth/register', { data: { username, password } })
  const res = await request.post('/auth/login', {
    data: { username, password },
  })
  expect(res.ok()).toBeTruthy()
  const { token } = (await res.json()) as { token: string }

  await page.addInitScript(
    ([t, name]) => {
      localStorage.setItem('orion.jwt', t)
      localStorage.setItem('orion.username', name)
    },
    [token, username] as const,
  )
  return { username, token }
}

/** 開 user 選單(expanded sidebar 的按鈕 accessible name = username)→ 點 Settings。 */
export async function openSettings(
  page: Page,
  username: string,
): Promise<void> {
  await page.getByRole('button', { name: username }).click()
  await page.getByRole('menuitem', { name: 'Settings' }).click()
}

/**
 * 點設定 modal 的分頁。scope 到 modal 的 <nav> + exact,避免撞到 modal 外的
 * header 齒輪(title="Settings")或子字串(如 'Settings')。
 */
export async function clickSettingsTab(
  page: Page,
  label: string,
): Promise<void> {
  await page
    .getByRole('navigation')
    .getByRole('button', { name: label, exact: true })
    .click()
}
