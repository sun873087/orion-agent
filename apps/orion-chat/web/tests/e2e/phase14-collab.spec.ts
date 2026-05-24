import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('create a collaboration in settings', async ({ page, request }) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'Collaborations')

  await page.getByPlaceholder('Collaboration name').fill('My Squad')
  await page.getByRole('button', { name: 'New', exact: true }).click()

  await expect(page.getByText('My Squad')).toBeVisible()
})
