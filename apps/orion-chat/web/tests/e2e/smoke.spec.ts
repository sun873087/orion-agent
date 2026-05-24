import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('logged-in user sees the chat shell', async ({ page, request }) => {
  await loginFreshUser(page, request)
  await page.goto('/')
  // 側欄品牌 + 開新對話按鈕(預設 locale=en)
  await expect(page.getByText('Orion')).toBeVisible()
  await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible()
})

test('unauthenticated user sees the login screen', async ({ page }) => {
  await page.goto('/')
  // 沒 token → Login 元件;至少有一個 password 欄位
  await expect(page.locator('input[type="password"]')).toBeVisible()
})
