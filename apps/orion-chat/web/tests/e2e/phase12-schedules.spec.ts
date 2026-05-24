import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('create a cron schedule in settings', async ({ page, request }) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'Schedules')

  await page.getByPlaceholder('Schedule name').fill('Daily summary')
  await page.getByRole('button', { name: 'New', exact: true }).click()

  await expect(page.getByText('Daily summary')).toBeVisible()
})
