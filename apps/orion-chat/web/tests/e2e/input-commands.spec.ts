import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('slash popover lists client commands for an active session', async ({
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
  await ta.fill('/com')
  // client 指令(需 active session)出現在 popover
  await expect(page.getByText('/compact')).toBeVisible()
})

test('@skill mention lists seeded skills', async ({ page, request }) => {
  const { token } = await loginFreshUser(page, request)
  const h = { Authorization: `Bearer ${token}` }
  await request.put('/skills/pw-research', {
    headers: h,
    data: { description: 'deep research', body: '# research' },
  })
  // 需要 active session,輸入框才 enabled
  await request.post('/sessions', { headers: h })
  await page.goto('/')

  const ta = page.getByPlaceholder('Reply to Orion…')
  await expect(ta).toBeVisible()
  await ta.fill('look @skill:pw')
  await expect(page.getByText('pw-research', { exact: true })).toBeVisible()
})
