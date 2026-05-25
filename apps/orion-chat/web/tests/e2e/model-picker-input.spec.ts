import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('model picker lives inside the input box and opens upward', async ({
  page,
  request,
}) => {
  await loginFreshUser(page, request)
  await page.goto('/')

  // 等 model catalog 載完再開新對話 — 否則 draft 拿不到預設 model,選擇器不顯示
  await page.waitForResponse(
    (r) => r.url().includes('/models') && r.request().method() === 'GET' && r.ok(),
  )

  // 開新對話 → 進入 welcome / draft 狀態,輸入框與選擇器同框
  await page.getByRole('button', { name: 'New chat', exact: true }).click()
  await expect(
    page.getByPlaceholder('Reply to Orion…'),
  ).toBeVisible()

  // 模型選擇器在輸入框內(title="Select model"),點開後列出 provider
  const picker = page.getByTitle('Select model')
  await expect(picker).toBeVisible()
  await picker.click()
  await expect(page.getByText('Anthropic', { exact: true })).toBeVisible()
})
