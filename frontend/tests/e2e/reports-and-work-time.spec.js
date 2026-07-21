import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


test('daily report reloads after switching tabs', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '统计报表')

  await expect(page.locator('.main-content')).toContainText('报工明细')
  await page.getByText('👷 员工计件', { exact: true }).click()
  await expect(page.locator('.main-content')).toContainText('员工计件')
  await page.getByText('📊 日报表', { exact: true }).click()
  await expect(page.locator('.main-content')).toContainText('报工明细')
  await expect(page.locator('.main-content')).toContainText('E2E-HANDOFF-001')
  expect(failures).toEqual([])
})

test('work-time route modal stays stable inside the viewport', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '工时管理')

  const routeCard = page.locator('.route-standard-card').filter({ hasText: 'E2E Standard Route' })
  await expect(routeCard).toBeVisible()
  await routeCard.getByRole('button', { name: '批量编辑' }).click()

  const modal = page.locator('.route-standard-modal')
  await expect(modal).toBeVisible()
  const firstBox = await modal.boundingBox()
  await page.waitForTimeout(350)
  const secondBox = await modal.boundingBox()
  expect(firstBox).not.toBeNull()
  expect(secondBox).not.toBeNull()
  expect(firstBox.y).toBeGreaterThanOrEqual(0)
  expect(firstBox.y + firstBox.height).toBeLessThanOrEqual((page.viewportSize()?.height || 720) + 2)
  expect(Math.abs(firstBox.y - secondBox.y)).toBeLessThan(2)
  expect(Math.abs(firstBox.x - secondBox.x)).toBeLessThan(2)
  expect(failures).toEqual([])
})


test('work-time record entry opens with order search and standard status', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '\u5de5\u65f6\u7ba1\u7406')

  await page.getByRole('button', { name: '\u5de5\u65f6\u6d41\u6c34', exact: true }).click()
  await page.getByRole('button', { name: '\u65b0\u589e\u5de5\u65f6\u6d41\u6c34', exact: true }).click()

  const modal = page.locator('.record-modal')
  await expect(modal).toBeVisible()
  await expect(modal).toContainText('\u8ba2\u5355\u53f7\uff08\u641c\u7d22\u9009\u62e9\uff09')
  const orderSelect = modal.locator('.order-search-group select')
  await orderSelect.selectOption({ index: 1 })
  await expect(modal).toContainText('\u6807\u51c6\u5339\u914d')
  const box = await modal.boundingBox()
  expect(box).not.toBeNull()
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.y + box.height).toBeLessThanOrEqual((page.viewportSize()?.height || 720) + 2)
  expect(failures).toEqual([])
})
