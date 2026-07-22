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

test('quality management loads every workflow tab without runtime failures', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '质量管理', '质量管理')

  const main = page.locator('.main-content')
  for (const label of [
    '质量工作台', '检验任务', '检验记录', '标准方案', '不合格品',
    'CAPA', '质量资源', '统计分析', '门禁规则',
  ]) {
    await main.locator('.qm-tabs').getByRole('button', { name: label, exact: true }).click()
    await expect(main.locator('.qm-body')).toBeVisible()
    await expect(main).not.toContainText('加载失败')
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


test('employee list renders assigned processes without administrator accounts', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '\u57fa\u7840\u8bbe\u7f6e', '\u57fa\u7840\u8bbe\u7f6e')
  await page.locator('.tab-btn').filter({ hasText: '\u5458\u5de5\u7ba1\u7406' }).click()
  await expect(page.locator('.main-content')).toContainText('\u666e\u901a\u5458\u5de5\u7ba1\u7406')

  await page.locator('.card-header input.form-input').first().fill('e2eworker')
  await page.locator('.card-header').getByRole('button', { name: '\u641c\u7d22', exact: true }).click()
  const workerRow = page.locator('.data-table tbody tr').filter({ hasText: 'E2E Current Worker' })
  await expect(workerRow).toContainText('E2E Welding')
  await expect(workerRow).toContainText('E2E Drilling')
  await expect(page.locator('.main-content')).not.toContainText('E2E Administrator')
  expect(failures).toEqual([])
})

test('performance page filters by position and opens score evidence', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '\u7ee9\u6548\u7ba1\u7406', '\u7ee9\u6548\u91cf\u5316\u7ba1\u7406')

  const generateButton = page.getByRole('button', { name: '\u751f\u6210/\u91cd\u7b97\u672c\u6708\u8bc4\u5206', exact: true })
  await expect(generateButton).toBeVisible()
  await generateButton.click()

  const main = page.locator('.main-content')
  const scoreRow = main.locator('.data-table tbody tr').filter({ hasText: 'E2E Current Worker' })
  await expect(scoreRow).toBeVisible()
  const positionSelect = main.locator('select.form-input').nth(1)
  const positionValue = await positionSelect.locator('option').filter({ hasText: 'E2E Production Position' }).getAttribute('value')
  await positionSelect.selectOption(positionValue)
  await expect(scoreRow).toContainText('E2E Production Position')
  await expect(scoreRow).toContainText(/1\/2|2\/2/)

  await scoreRow.getByRole('button', { name: '\u4f9d\u636e' }).click()
  const modal = page.locator('.modal').filter({ hasText: '\u8bc4\u5206\u4f9d\u636e - E2E Current Worker' })
  await expect(modal).toBeVisible()
  await expect(modal).toContainText('\u5c97\u4f4d\u5185\u6392\u540d')
  await expect(modal).toContainText('\u5c97\u4f4d\u6700\u9ad8\u4ea7\u91cf')
  expect(failures).toEqual([])
})
