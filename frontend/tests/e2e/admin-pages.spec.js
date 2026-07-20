import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


test('administrator can open all previously blank critical pages', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)

  for (const [label, expected] of [
    ['系统设置', '系统设置'],
    ['基础设置', '基础设置'],
    ['工资核算', '计件工资'],
    ['数据分析', '数据分析'],
    ['绩效管理', '绩效量化管理'],
    ['工时管理', '工时管理'],
  ]) {
    await openSidebarPage(page, label, expected)
  }

  expect(failures).toEqual([])
})

test('order list renders active and archived E2E orders', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '生产管理', '订单管理')

  await page.getByPlaceholder('搜索订单号/产品/客户...').fill('E2E-ORDER-001')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(page.locator('.order-table')).toContainText('E2E-ORDER-001')

  await page.getByPlaceholder('搜索订单号/产品/客户...').fill('')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.locator('.filter-select').first().selectOption('completed')
  await expect(page.locator('.order-table')).toContainText('E2E-COMPLETE-ORDER')
  expect(failures).toEqual([])
})
