import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('enter plan mode, review submitted plan, approve', async ({
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
  // 進 plan mode → indicator
  await page.getByRole('button', { name: 'Plan', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Planning' })).toBeVisible()

  // 模擬模型 submit plan(透過 API),reload 後 modal 出現
  await request.post(`/sessions/${sid}/plan/submit`, {
    headers: auth,
    data: { content: '# Plan\n\n1. Investigate\n2. Implement' },
  })
  await page.reload()
  await expect(page.getByText('Review plan')).toBeVisible()
  await expect(page.getByText('Investigate')).toBeVisible()

  // approve → modal 消失,狀態 inactive
  await page.getByRole('button', { name: 'Approve & run' }).click()
  await expect(page.getByText('Review plan')).toHaveCount(0)
})
