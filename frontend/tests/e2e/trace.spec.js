import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


test('product trace follows a serial item and its order without runtime failures', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '生产管理', '生产管理')

  const main = page.locator('.main-content')
  await main.locator('.tab-btn').filter({ hasText: '产品追溯' }).click()
  await expect(main).toContainText('暂无追溯结果')

  await main.getByPlaceholder('输入产品序列号').fill('E2E-HANDOFF-001')
  await main.getByRole('button', { name: '🔍 追溯', exact: true }).click()
  await expect(main).toContainText('序列号追溯结果')
  await expect(main).toContainText('E2E-HANDOFF-001')
  await expect(main).toContainText('报工记录 (2)')
  await expect(main).toContainText('E2E Previous Worker')
  await expect(main).toContainText('E2E Current Worker')
  await expect(main).toContainText('订单级库存流水')

  await main.getByRole('button', { name: /查看订单 E2E-HANDOFF-ORDER 全部产品/ }).click()
  await expect(main).toContainText('订单号追溯结果')
  await expect(main).toContainText('产品列表 (1)')
  await expect(main).toContainText('E2E-HANDOFF-001')
  expect(failures).toEqual([])
})


test('product trace remains contained on a mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)

  const main = page.locator('.main-content')
  await page.locator('.sidebar').getByText('生产管理', { exact: true }).evaluate(element => element.click())
  await expect(main).toContainText('生产管理')
  await main.locator('.tab-btn').filter({ hasText: '产品追溯' }).evaluate(element => element.click())
  await main.getByPlaceholder('输入产品序列号').fill('E2E-HANDOFF-001')
  await main.getByRole('button', { name: '🔍 追溯', exact: true }).click()
  await expect(main).toContainText('序列号追溯结果')

  const overflow = await main.locator('.trace-page').evaluate(element => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }))
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
  expect(failures).toEqual([])
})
