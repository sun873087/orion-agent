import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('set a per-session budget cap from the header', async ({
  page,
  request,
}) => {
  const { token } = await loginFreshUser(page, request)
  const auth = { Authorization: `Bearer ${token}` }
  const created = await (
    await request.post('/sessions', { headers: auth })
  ).json()
  const sid = created.session_id

  await page.goto('/')
  // header 預算按鈕 → prompt 接受 "5"
  page.on('dialog', (d) => void d.accept('5'))
  await page.getByRole('button', { name: 'Budget', exact: true }).click()

  // 後端已存上限
  await expect
    .poll(async () => {
      const r = await request.get(`/sessions/${sid}/budget`, { headers: auth })
      return (await r.json()).budget_usd_cap
    })
    .toBe(5)
})
