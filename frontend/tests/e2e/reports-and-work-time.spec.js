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
