import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('model settings tab lists providers and picks a default', async ({
  page,
  request,
}) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'Model')

  // provider 分組 + 可點的 model
  await expect(page.getByText('Anthropic', { exact: true })).toBeVisible()
  const haiku = page.getByRole('button', { name: /Claude Haiku/ })
  await haiku.click()
  // 寫進 localStorage preferredModel
  const stored = await page.evaluate(() =>
    localStorage.getItem('orion.preferred_model'),
  )
  expect(stored).toBe('claude-haiku-4-5')
})

test('/schedule deep-links the schedules settings tab', async ({
  page,
  request,
}) => {
  const { token } = await loginFreshUser(page, request)
  await request.post('/sessions', {
    headers: { Authorization: `Bearer ${token}` },
  })
  await page.goto('/')

  const ta = page.getByPlaceholder('Reply to Orion…')
  await expect(ta).toBeVisible()
  await ta.fill('/schedule')
  // 點 popover 的指令按鈕(避免撞到 textarea 的同值文字)
  await page.getByRole('button', { name: /^\/schedule\b/ }).click()
  // 設定開到 schedules tab — SchedulesPanel 專屬的 'Schedule name' 輸入框可見
  await expect(page.getByPlaceholder('Schedule name')).toBeVisible()
})
