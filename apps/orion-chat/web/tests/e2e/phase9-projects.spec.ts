import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('create a project in settings', async ({ page, request }) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'Projects')

  await page.getByPlaceholder('Project name').fill('My E2E Project')
  await page.getByRole('button', { name: 'New', exact: true }).click()

  await expect(page.getByText('My E2E Project')).toBeVisible()
})
