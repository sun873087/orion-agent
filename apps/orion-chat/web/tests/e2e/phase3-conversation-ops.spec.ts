import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('branch a session creates a second conversation', async ({
  page,
  request,
}) => {
  const { token } = await loginFreshUser(page, request)
  await request.post('/sessions', {
    headers: { Authorization: `Bearer ${token}` },
  })
  await page.goto('/')
  await expect(page.getByText('Untitled')).toHaveCount(1)

  // 分支 → 出現第二個 session
  await page.getByRole('button', { name: 'Branch', exact: true }).click()
  await expect(page.getByText('Untitled')).toHaveCount(2)
})
