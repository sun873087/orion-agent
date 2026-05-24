import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('add an MCP server in connections', async ({ page, request }) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'Connections')

  await page.getByPlaceholder('name').fill('docs')
  await page.getByPlaceholder('https://…').fill('https://mcp.example.com')
  await page.getByRole('button', { name: 'New', exact: true }).click()

  await expect(page.getByText('docs')).toBeVisible()
  await expect(page.getByText('https://mcp.example.com')).toBeVisible()
})
