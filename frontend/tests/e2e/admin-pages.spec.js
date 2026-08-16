import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


test('administrator can open all previously blank critical pages', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)

  for (const [label, expected] of [
    ['系统设置', '系统设置'],
    ['基础设置', '基础设置'],
    ['工资核算', '工资批次台账'],
    ['数据分析', '数据分析'],
    ['绩效管理', '绩效管理'],
    ['工时管理', '工时管理'],
  ]) {
    await openSidebarPage(page, label, expected)
  }

  expect(failures).toEqual([])
})

test('company profile creates a versioned revision with audit history access', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '系统设置', '系统设置')

  const main = page.locator('.main-content')
  await main.locator('.tab-btn').filter({ hasText: '公司资料' }).click()
  await expect(main.locator('.company-info-page')).toBeVisible()
  await expect(main).toContainText('完整历史')

  const saveButton = main.getByRole('button', { name: '保存资料', exact: true })
  await expect(saveButton).toBeDisabled()
  await main.getByLabel('公司名称').fill('E2E 版本化公司资料')
  await expect(saveButton).toBeEnabled()
  await saveButton.click()

  await expect(main).toContainText('V2')
  const latestRevision = main.locator('.history-table tbody tr').first()
  await expect(latestRevision).toContainText('E2E 版本化公司资料')
  await expect(latestRevision).toContainText('公司名称')

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 1440, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    const shell = main.locator('.company-info-page')
    const box = await shell.boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
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

test('performance page creates a V2 draft and opens immutable score evidence', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await openSidebarPage(page, '\u7ee9\u6548\u7ba1\u7406', '\u7ee9\u6548\u7ba1\u7406')

  const main = page.locator('.main-content')
  await expect(main).not.toContainText('\u751f\u6210/\u91cd\u7b97\u672c\u6708\u8bc4\u5206')
  await expect(main).not.toContainText('\u5c97\u4f4d\u6700\u9ad8\u4ea7\u91cf')
  await main.getByRole('button', { name: '\u6279\u6b21\u5ba1\u6279', exact: true }).click()
  await main.getByRole('button', { name: '\u65b0\u5efa\u6708\u5ea6\u8349\u7a3f', exact: true }).click()

  await expect(main).toContainText('\u8349\u7a3f')
  await expect(main).toContainText('V1')
  const scoreRow = main.locator('.batch-members-table tbody tr').filter({ hasText: 'E2E Current Worker' })
  await expect(scoreRow).toBeVisible()
  await expect(scoreRow).toContainText('E2E Production Position')

  await scoreRow.getByRole('button', { name: '\u4f9d\u636e', exact: true }).click()
  const modal = page.locator('.modal').filter({ hasText: '\u8bc4\u5206\u4f9d\u636e - E2E Current Worker' })
  await expect(modal).toBeVisible()
  await expect(modal).toContainText('\u5c97\u4f4d\u76ee\u6807\u4ea7\u91cf')
  await expect(modal).not.toContainText('\u5c97\u4f4d\u6700\u9ad8\u4ea7\u91cf')
  await modal.getByRole('button', { name: '\u5173\u95ed', exact: true }).click()
  await page.waitForTimeout(3000)
  for (const viewport of [{ width: 390, height: 844 }, { width: 768, height: 1024 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport)
    await page.waitForTimeout(350)
    await page.locator('.table-wrap').evaluateAll(elements => elements.forEach(element => { element.scrollLeft = 0 }))
    const shell = main.locator('.performance-page')
    await expect(shell).toBeVisible()
    const box = await shell.boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
    await page.screenshot({ path: `test-results/performance-${viewport.width}x${viewport.height}.png`, fullPage: true })
  }
  expect(failures).toEqual([])
})

test('process quality disposal uses server pagination and previews waiver impact', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  let disposalPerPage = null
  let previewPayload = null

  await page.route(/\/api\/process-quality-evaluations\/tasks(?:\?.*)?$/, async route => {
    const request = route.request()
    const url = new URL(request.url())
    disposalPerPage = url.searchParams.get('per_page')
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{
          id: 9001, order_id: 501, order_no: 'E2E-PQE-PREVIEW', order_status: 'completed',
          order_deleted_at: '', serial_no: 'SN-PQE-001', product_name: 'E2E Quality Part',
          product_code: 'E2E-QP', target_process_name: 'E2E Welding', target_user_name: 'E2E Current Worker',
          evaluator_process_name: 'E2E Drilling', evaluator_name: 'E2E Current Worker', evaluator_user_id: 2,
          template_snapshot: { name: 'E2E Template' }, is_required: 1, attribution_type: 'worker',
          status: 'pending', created_at: '2026-07-26 08:00:00', age_hours: 30, age_level: 'warning',
        }],
        total: 1, page: 1, per_page: 50, pending_count: 1, pending_required_count: 1,
      }),
    })
  })
  await page.route('**/api/process-quality-evaluations/tasks/disposal-summary', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      required_pending: 1, overdue_24h: 1, overdue_72h: 0, completed_order_required: 1,
      affected_workers: 1,
      waiver_policy: {
        can_waive_live: true,
        historical_reasons: [{ code: 'completed_order_history', label: '已完成订单历史遗留' }],
        live_reasons: [{ code: 'task_generated_in_error', label: '评价任务错误生成' }],
      },
    }),
  }))
  await page.route('**/api/process-quality-evaluations/tasks/waiver-preview', async route => {
    previewPayload = route.request().postDataJSON()
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        task_ids: [9001], task_count: 1, required_count: 1, optional_count: 0,
        affected_worker_count: 1, waiver_scope: 'historical', has_mixed_scopes: false,
        requires_live_permission: false, can_submit: true,
        orders: [{ order_id: 501, order_no: 'E2E-PQE-PREVIEW', order_status: 'completed', waiver_scope: 'historical', task_count: 1, required_count: 1, optional_count: 0 }],
        warnings: ['本次将豁免 1 条必评任务，评价数据将永久缺失并保留审计记录。'],
      }),
    })
  })

  await loginAdmin(page)
  await openSidebarPage(page, '工序质量评价', '工序质量评价')
  const main = page.locator('.main-content')
  await main.locator('.pqe-tabs').getByRole('button', { name: /任务处置/ }).click()
  await expect.poll(() => disposalPerPage).toBe('50')
  await main.locator('.pqe-wide tbody input[type="checkbox"]').check()
  await main.getByRole('button', { name: '豁免选中任务', exact: true }).click()

  const modal = page.locator('.modal').filter({ hasText: '豁免评价任务' })
  await expect(modal).toBeVisible()
  await expect(modal).toContainText('影响任务')
  await expect(modal).toContainText('E2E-PQE-PREVIEW')
  await expect(modal).toContainText('永久缺失')
  expect(previewPayload).toEqual({ task_ids: [9001] })
  await modal.getByRole('button', { name: '取消', exact: true }).click()
  expect(failures).toEqual([])
})
