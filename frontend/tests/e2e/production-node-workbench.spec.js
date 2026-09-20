import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


test('production node workbench remains viewport-fixed and responsive', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const nodes = Array.from({ length: 25 }, (_, index) => ({
    id: index + 1,
    process_id: index < 10 ? 7 : 8,
    process_name: index < 10 ? '焊接' : '铆接',
    node_code: `NODE-${String(index + 1).padStart(2, '0')}`,
    node_name: `生产节点-${String(index + 1).padStart(2, '0')}`,
    status: 'active',
    capacity_mode: 'exclusive',
    calendar_id: 1,
  }))
  await page.route(/\/api\/production-nodes(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ nodes }),
  }))
  await page.setViewportSize({ width: 1366, height: 768 })
  await loginAdmin(page)
  await openSidebarPage(page, '生产管理', '生产管理')
  const main = page.locator('.main-content')
  await main.locator('.tab-btn').filter({ hasText: '生产排程' }).click()
  await expect(main).toContainText('生产排程')
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))

  const trigger = page.getByRole('button', { name: /生产节点管理/ })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '生产节点管理' })
  await expect(dialog).toBeVisible()

  const desktopBox = await dialog.boundingBox()
  expect(desktopBox.x).toBeGreaterThanOrEqual(0)
  expect(desktopBox.y).toBeGreaterThanOrEqual(0)
  expect(desktopBox.x + desktopBox.width).toBeLessThanOrEqual(1366)
  expect(desktopBox.y + desktopBox.height).toBeLessThanOrEqual(768)
  await expect(dialog.locator('.node-workbench__header')).toBeVisible()
  await expect(dialog.locator('.node-workbench__tabs')).toBeVisible()
  await expect(dialog.locator('.node-workbench__footer')).toBeVisible()
  await expect(dialog.locator('[data-test^="node-item-"]')).toHaveCount(25)
  await dialog.getByRole('searchbox', { name: '搜索生产节点' }).fill('NODE-25')
  await expect(dialog.locator('[data-test^="node-item-"]')).toHaveCount(1)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(dialog).toHaveClass(/node-workbench/)
  await expect(dialog.getByLabel('选择生产节点')).toBeVisible()
  const mobileBox = await dialog.boundingBox()
  expect(Math.abs(mobileBox.width - 390)).toBeLessThanOrEqual(1)
  expect(Math.abs(mobileBox.height - 844)).toBeLessThanOrEqual(1)

  await dialog.getByRole('button', { name: '关闭生产节点管理' }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.locator(':focus')).toBeVisible()

  await dialog.getByRole('button', { name: '关闭生产节点管理' }).click()
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
  expect(failures).toEqual([])
})
