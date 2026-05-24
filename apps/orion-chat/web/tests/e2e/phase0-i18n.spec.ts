import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('switching language re-renders the whole UI', async ({
  page,
  request,
}) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  // 預設 locale=en
  await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible()

  await openSettings(page, username)
  await clickSettingsTab(page, 'Settings')

  // 語言下拉(含「日本語」選項的那顆 select)→ 切 ja
  const langSelect = page
    .locator('select')
    .filter({ has: page.getByRole('option', { name: '日本語' }) })
  await langSelect.selectOption('ja')

  // 切換後設定分頁 label 立即本地化(Skills → スキル)
  await expect(
    page.getByRole('navigation').getByRole('button', { name: 'スキル' }),
  ).toBeVisible()

  // 關閉設定後,側欄也變日文
  await page.keyboard.press('Escape')
  await expect(
    page.getByRole('button', { name: '新しいチャット' }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'New chat' })).toHaveCount(0)
})
