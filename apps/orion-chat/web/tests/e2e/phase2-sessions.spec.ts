import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('rename and star a session from the sidebar', async ({
  page,
  request,
}) => {
  const { token } = await loginFreshUser(page, request)
  // 先用 API 建一個 session(帶 token),這樣 sidebar 會列出它
  const res = await request.post('/sessions', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(res.ok()).toBeTruthy()

  await page.goto('/')

  // 未命名 session 出現
  await expect(page.getByText('Untitled')).toBeVisible()

  // rename(window.prompt → 自動接受帶新標題)
  page.on('dialog', (d) => void d.accept('Renamed E2E'))
  await page.getByRole('button', { name: 'Rename', exact: true }).click()
  await expect(page.getByText('Renamed E2E')).toBeVisible()

  // star → aria-label 由 Star 變 Unstar
  await page.getByRole('button', { name: 'Star', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Unstar', exact: true }),
  ).toBeVisible()
})
