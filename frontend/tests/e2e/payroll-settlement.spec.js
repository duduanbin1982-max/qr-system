import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'

test.use({ timezoneId: 'Asia/Shanghai' })

async function json(route, body, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('payroll settlement completes export, receipt, reconciliation, and close', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const operations = []
  const batch = {
    id: 31, payroll_month: '2026-09', version: 2, status: 'confirmed',
    payable_wage_cents: 12500, prepared_by_name: '财务制单员',
  }
  const exportBatch = {
    id: 71, settlement_id: 51, export_version: 1, status: 'active',
    row_count: 1, total_cents: 12500, content_sha256: 'a'.repeat(64),
    created_at: '2026-09-03 09:00:00',
  }
  const settlement = {
    id: 51, batch_id: 31, status: 'not_exported', row_version: 0,
    expected_total_cents: 12500, successful_paid_cents: 0, difference_cents: 12500,
    blocking_difference_count: 0, current_export: null, exports: [],
    receipt_batches: [], latest_reconciliation: null, can_close: false, close_record: null,
  }

  await page.addInitScript(() => localStorage.setItem('wageActiveTab', 'settlement'))
  await page.route('**/api/payroll/batches?**', route => json(route, { batches: [batch] }))
  await page.route('**/api/payroll/batches/31/settlement', route => json(route, settlement))
  await page.route('**/api/payroll/batches/31/settlement/exports', route => {
    operations.push({ action: 'export', body: route.request().postDataJSON() })
    Object.assign(settlement, {
      status: 'exported', row_version: 1, current_export: exportBatch,
      exports: [exportBatch], difference_cents: 12500,
    })
    return json(route, exportBatch, 201)
  })
  await page.route('**/api/payroll/settlement/exports/71/receipts', route => {
    operations.push({ action: 'receipt', body: route.request().postData() })
    const receipt = {
      id: 81, export_batch_id: 71, source_filename: 'receipt.csv', status: 'accepted',
      accepted_row_count: 1, failed_row_count: 0, content_sha256: 'b'.repeat(64),
      uploaded_at: '2026-09-03 10:00:00', invalid_items: [],
    }
    Object.assign(settlement, {
      status: 'receipting', row_version: 2, receipt_batches: [receipt],
      latest_reconciliation: null, can_close: false,
    })
    return json(route, receipt, 201)
  })
  await page.route('**/api/payroll/settlements/51/reconcile', route => {
    operations.push({ action: 'reconcile', body: route.request().postDataJSON() })
    const run = {
      id: 91, settlement_id: 51, export_batch_id: 71, run_version: 1,
      status: 'reconciled', expected_total_cents: 12500, successful_paid_cents: 12500,
      difference_cents: 0, blocking_count: 0, receipt_digest: 'c'.repeat(64),
      executed_at: '2026-09-03 10:05:00', items: [],
    }
    Object.assign(settlement, {
      status: 'reconciled', row_version: 3, successful_paid_cents: 12500,
      difference_cents: 0, blocking_difference_count: 0,
      latest_reconciliation: run, can_close: true,
    })
    return json(route, run, 201)
  })
  await page.route('**/api/payroll/settlements/51/close', route => {
    operations.push({ action: 'close', body: route.request().postDataJSON() })
    const closeRecord = { id: 101, settlement_id: 51, close_reason: '财务核对完成' }
    Object.assign(settlement, {
      status: 'closed', row_version: 4, can_close: false, close_record: closeRecord,
    })
    return json(route, closeRecord, 201)
  })

  await loginAdmin(page)
  await openSidebarPage(page, '工资核算', '导出对账')
  const main = page.locator('.main-content')

  await main.getByTestId('create-payment-list').click()
  await expect(main.getByTestId('export-version-list')).toContainText('V1')
  await expect(main.getByTestId('export-version-list')).toContainText('当前有效')

  await main.getByTestId('receipt-file').setInputFiles({
    name: 'receipt.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'payment_reference,employee_no,employee_name,paid_amount,payment_status\n'
      + 'PAY00000031V0001L0000000001,EMP-001,张三,125.00,success\n',
    ),
  })
  await main.getByTestId('upload-receipt').click()
  await expect(main).toContainText('receipt.csv')

  await main.getByTestId('run-reconciliation').click()
  await expect(main).toContainText('当前回执与应付金额一致')
  await expect(main.getByTestId('close-summary')).toContainText('最终金额 ¥125.00')
  await expect(main.getByTestId('close-summary')).toContainText('当前导出版本 V1')
  await expect(main.getByTestId('close-summary')).toContainText('回执批次数量 1')
  await expect(main.getByTestId('close-summary')).toContainText('对账运行版本 第 1 次')

  page.on('dialog', dialog => {
    if (dialog.type() === 'prompt') return dialog.accept('财务核对完成')
    return dialog.accept()
  })
  await main.getByTestId('close-settlement').click()
  await expect(main).toContainText('结算已锁定')

  expect(operations.map(operation => operation.action)).toEqual([
    'export', 'receipt', 'reconcile', 'close',
  ])
  expect(operations[0].body.idempotency_key).toMatch(/^payroll-settlement-ui:export:/)
  expect(operations[1].body).toContain('payroll-settlement-ui:receipt:')
  expect(operations[2].body.idempotency_key).toMatch(/^payroll-settlement-ui:reconcile:/)
  expect(operations[3].body).toMatchObject({ row_version: 3, close_reason: '财务核对完成' })
  expect(operations[3].body.idempotency_key).toMatch(/^payroll-settlement-ui:close:/)
  expect(failures).toEqual([])
})
