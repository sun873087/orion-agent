import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('opening a new chat re-fetches the model catalog', async ({
  page,
  request,
}) => {
  let modelsCalls = 0
  page.on('request', (r) => {
    if (r.url().includes('/models') && r.method() === 'GET') modelsCalls++
  })

  await loginFreshUser(page, request)
  await page.goto('/')

  // 初次載入會抓一次 /models
  await expect.poll(() => modelsCalls).toBeGreaterThanOrEqual(1)
  const before = modelsCalls

  // 點 New chat → 強制重抓 /models
  await page.getByRole('button', { name: 'New chat', exact: true }).click()
  await expect.poll(() => modelsCalls).toBeGreaterThan(before)
})
