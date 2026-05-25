import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('general tab merges avatar / appearance / language / instructions', async ({
  page,
  request,
}) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'General')

  // ICON / avatar 設定
  await expect(page.getByRole('button', { name: 'Pick image' })).toBeVisible()
  // 自訂指令(同一個 tab 內)
  await expect(page.getByPlaceholder(/senior Python engineer/)).toBeVisible()
  // 語言下拉(同一個 tab 內)
  await expect(
    page
      .locator('select')
      .filter({ has: page.getByRole('option', { name: '日本語' }) }),
  ).toBeVisible()

  // 舊的「Instructions」「Settings」分頁已不存在(合併掉了)
  const nav = page.getByRole('navigation')
  await expect(
    nav.getByRole('button', { name: 'Instructions', exact: true }),
  ).toHaveCount(0)
  await expect(
    nav.getByRole('button', { name: 'Settings', exact: true }),
  ).toHaveCount(0)
})
