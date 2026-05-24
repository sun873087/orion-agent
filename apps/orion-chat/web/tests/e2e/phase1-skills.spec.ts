import { expect, test } from '@playwright/test'
import { clickSettingsTab, loginFreshUser, openSettings } from './helpers'

test('create then delete a skill through the UI', async ({ page, request }) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'Skills')

  // 新增(exact 避免撞 'New chat')
  await page.getByRole('button', { name: 'New', exact: true }).click()
  await page.getByPlaceholder('my-skill').fill('pw-skill')
  await page.getByRole('button', { name: 'Save', exact: true }).click()

  // 出現在列表
  await expect(page.getByText('pw-skill')).toBeVisible()

  // 刪除(confirm 對話框自動接受)
  page.on('dialog', (d) => void d.accept())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByText('pw-skill')).toHaveCount(0)
})

test('soul note persists across reload', async ({ page, request }) => {
  const { username } = await loginFreshUser(page, request)
  await page.goto('/')

  await openSettings(page, username)
  await clickSettingsTab(page, 'Soul')

  const note = 'They prefer terse, code-first answers.'
  await page.getByPlaceholder(/remember about you/i).fill(note)
  await page.getByRole('button', { name: 'Save', exact: true }).click()

  // reload → 重開 Soul 分頁,內容還在(後端持久化;write_soul 會補尾端換行)
  await page.reload()
  await openSettings(page, username)
  await clickSettingsTab(page, 'Soul')
  await expect(page.getByPlaceholder(/remember about you/i)).toHaveValue(
    /terse, code-first answers\./,
  )
})
