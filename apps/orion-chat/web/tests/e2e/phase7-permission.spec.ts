import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('toggle permission mode ask <-> act', async ({ page, request }) => {
  const { token } = await loginFreshUser(page, request)
  const auth = { Authorization: `Bearer ${token}` }
  const created = await (
    await request.post('/sessions', { headers: auth })
  ).json()
  const sid = created.session_id

  await page.goto('/')
  // 預設 Ask
  await expect(
    page.getByRole('button', { name: 'Ask', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  // 切到 Auto
  await expect(
    page.getByRole('button', { name: 'Auto', exact: true }),
  ).toBeVisible()

  await expect
    .poll(async () => {
      const r = await request.get(`/sessions/${sid}/permission-mode`, {
        headers: auth,
      })
      return (await r.json()).mode
    })
    .toBe('act')
})
