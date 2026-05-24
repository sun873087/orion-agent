import { expect, test } from '@playwright/test'
import { loginFreshUser } from './helpers'

test('detail panel toggles and shows sections', async ({ page, request }) => {
  const { token } = await loginFreshUser(page, request)
  await request.post('/sessions', {
    headers: { Authorization: `Bearer ${token}` },
  })
  await page.goto('/')

  await page.getByRole('button', { name: 'Details', exact: true }).click()
  await expect(page.getByText('Progress')).toBeVisible()
  await expect(page.getByText('Skills used')).toBeVisible()
  await expect(page.getByText('Tokens & cost')).toBeVisible()
})
