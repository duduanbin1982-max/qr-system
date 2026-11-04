import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'

const at = hour => `2026-11-04 ${hour}:00:00`

function traceResult(quality, inventory, shipment) {
  return {
    order: {
      id: 1, order_no: 'TIMELINE-ORDER', status: 'completed', quantity: 2,
      product_name: '时间线测试产品', created_at: at('08'),
    },
    items: [],
    work_records: [{ id: 1, process_name: '焊接', worker_name: '杜', quantity: 2, status: 'approved', created_at: at('09') }],
    quality_inspections: [{ id: 1, process_name: '终检', result: 'pass', quantity_checked: 2, inspected_at: at(quality) }],
    inventory_logs: [{ id: 1, product_name: '产品', type: 'in', quantity: 2, created_at: at(inventory) }],
    shipments: [{ id: 1, shipment_no: 'TIMELINE-SHIP', status: 'completed', order_quantity: 2, completed_at: at(shipment) }],
    meta: { page: 1, total_pages: 1 },
  }
}

async function openTrace(page) {
  await loginAdmin(page)
  await openSidebarPage(page, '生产管理', '生产管理')
  const main = page.locator('.main-content')
  await main.locator('.tab-btn').filter({ hasText: '产品追溯' }).click()
  await main.getByRole('button', { name: '📋 订单号追溯', exact: true }).click()
  return main
}

async function search(main, orderNo = 'TIMELINE-ORDER') {
  await main.getByPlaceholder('输入订单号').fill(orderNo)
  await main.getByRole('button', { name: '🔍 追溯', exact: true }).click()
}

// The real app/login/server is used. Only the trace response is controlled so
// historical edge cases do not require creating inconsistent business records.
for (const [name, quality, inventory, shipment, labels] of [
  ['inspection before inventory', '10', '11', '12', ['终检 质检', '入库 · 产品', '发货 · TIMELINE-SHIP']],
  ['inventory before inspection', '12', '10', '13', ['入库 · 产品', '终检 质检', '发货 · TIMELINE-SHIP']],
  ['shipment before later inspection', '12', '11', '10', ['发货 · TIMELINE-SHIP', '入库 · 产品', '终检 质检']],
]) {
  test(`lifecycle follows actual chronology: ${name}`, async ({ page }) => {
    const failures = observeRuntimeFailures(page)
    const input = traceResult(quality, inventory, shipment)
    await page.route('**/api/trace/order/TIMELINE-ORDER?**', route => route.fulfill({ json: input }))
    const main = await openTrace(page)
    await search(main)
    const timeline = main.getByTestId('trace-lifecycle')
    await expect(timeline.locator('strong')).toHaveText(['订单创建', '焊接', ...labels])
    await expect(timeline).toContainText('杜 · +2')
    await expect(timeline).toContainText('合格 · 抽检 2')
    await expect(timeline).toContainText('数量 2')
    expect(failures).toEqual([])
  })
}

test('equal times, duplicate IDs and missing times remain stable after replacing a trace result', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const keyWarnings = []
  page.on('console', message => {
    if (/duplicate.*key/i.test(message.text())) keyWarnings.push(message.text())
  })
  const input = traceResult('10', '10', '10')
  input.order.created_at = at('10')
  input.work_records = [
    { id: 10, process_name: '报工10', created_at: at('10') },
    { id: 2, process_name: '报工2-A', created_at: at('10') },
    { id: 2, process_name: '报工2-B', created_at: at('10') },
    { id: 3, process_name: '缺时工序', created_at: null },
    { id: 4, process_name: '坏时工序', created_at: 'invalid' },
  ]
  await page.route('**/api/trace/order/TIMELINE-ORDER?**', route => route.fulfill({ json: input }))
  const main = await openTrace(page)
  await search(main)
  const timeline = main.getByTestId('trace-lifecycle')
  await expect(timeline.locator('strong')).toHaveText([
    '订单创建', '报工2-A', '报工2-B', '报工10', '终检 质检',
    '入库 · 产品', '发货 · TIMELINE-SHIP', '缺时工序', '坏时工序',
  ])
  await expect(timeline.locator('.timeline-row').filter({ hasText: '时间缺失' })).toHaveCount(2)
  // The separate work-record card must still use the original API order.
  const workCard = main.locator('.trace-card').filter({ has: page.getByRole('heading', { name: '📝 报工记录 (5)', exact: true }) })
  await expect(workCard.locator('strong')).toHaveText(['报工10', '报工2-A', '报工2-B', '缺时工序', '坏时工序'])

  const replacement = traceResult('12', '10', '11')
  replacement.order.order_no = 'TIMELINE-NEXT'
  await page.route('**/api/trace/order/TIMELINE-NEXT?**', route => route.fulfill({ json: replacement }))
  await search(main, 'TIMELINE-NEXT')
  await expect(timeline.locator('strong')).toHaveText([
    '订单创建', '焊接', '入库 · 产品', '发货 · TIMELINE-SHIP', '终检 质检',
  ])
  expect(keyWarnings).toEqual([])
  expect(failures).toEqual([])
})
