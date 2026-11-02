import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


const materials = [
  { id: 101, name: '物料审计A', quantity: 20, unit: '件', safe_stock: 0 },
  { id: 102, name: '物料审计B', quantity: 200, unit: '件', safe_stock: 0 },
]

async function openMaterials(page) {
  await page.route('**/api/materials?**', route => route.fulfill({
    json: { materials, total: 2, summary: {}, material_types: [] },
  }))
  await page.route('**/api/suppliers?**', route => route.fulfill({ json: { suppliers: [], total: 0 } }))
  await page.route('**/api/materials/*/consumptions?**', route => route.fulfill({
    json: { consumptions: [], total: 0 },
  }))
  await loginAdmin(page)
  await openSidebarPage(page, '生产管理', '订单管理')
  await page.locator('.tab-btn').filter({ hasText: '物料管理' }).click()
  await expect(page.locator('.data-table:visible')).toContainText('物料审计A')
}

test('clearing a selected consumption order sends an unbound consumption', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await page.route('**/api/orders?**', route => route.fulfill({
    json: { orders: [{ id: 77, order_no: 'AUDIT-ORDER', product_name: '审计产品' }], total: 1 },
  }))
  await page.route('**/api/materials/101/consumptions', route => route.fulfill({
    json: { id: 401, new_quantity: 19 },
  }))
  await openMaterials(page)
  const row = page.locator('.data-table tbody tr').filter({ hasText: '物料审计A' })
  await row.getByRole('button', { name: '消耗', exact: true }).click()
  const modal = page.locator('.modal').filter({ hasText: '物料消耗 — 物料审计A' })
  const search = modal.getByPlaceholder('搜索订单号...')
  await search.fill('AUDIT')
  await modal.locator('.combobox-item').filter({ hasText: 'AUDIT-ORDER' }).click()
  await expect(search).toHaveValue('AUDIT-ORDER 审计产品')
  await search.fill('')
  await modal.getByPlaceholder('消耗数量').fill('1')
  const saved = page.waitForRequest(request => (
    request.method() === 'POST'
    && new URL(request.url()).pathname === '/api/materials/101/consumptions'
  ))
  await modal.getByRole('button', { name: '确认消耗' }).click()
  expect((await saved).postDataJSON()).toMatchObject({ order_id: null, quantity: 1 })
  await expect(modal).toContainText('库存: 19 件')
  expect(failures).toEqual([])
})

test('a late stock response leaves a newly opened material form intact', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  let releaseStock
  const stockGate = new Promise(resolve => { releaseStock = resolve })
  await page.route('**/api/materials/101/stock', async route => {
    await stockGate
    await route.fulfill({ json: { new_quantity: 24 } })
  })
  await openMaterials(page)
  try {
    const rows = page.locator('.data-table tbody tr')
    await rows.filter({ hasText: '物料审计A' }).getByRole('button', { name: '出入库' }).click()
    const oldModal = page.locator('.modal').filter({ hasText: '出入库 — 物料审计A' })
    await oldModal.locator('input[type="number"]').fill('4')
    const started = page.waitForRequest('**/api/materials/101/stock')
    await oldModal.getByRole('button', { name: '确认', exact: true }).click()
    await started
    await oldModal.getByRole('button', { name: '取消' }).click()
    await rows.filter({ hasText: '物料审计B' }).getByRole('button', { name: '出入库' }).click()
    const currentModal = page.locator('.modal').filter({ hasText: '出入库 — 物料审计B' })
    await currentModal.locator('input[type="number"]').fill('8')
    const finished = page.waitForResponse('**/api/materials/101/stock')
    releaseStock()
    await (await finished).finished()
    await page.evaluate(() => new Promise(resolve => {
      requestAnimationFrame(() => requestAnimationFrame(resolve))
    }))
    await expect(currentModal).toBeVisible()
    await expect(currentModal).toContainText('当前库存: 200 件')
    await expect(currentModal.locator('input[type="number"]')).toHaveValue('8')
    expect(failures).toEqual([])
  } finally {
    releaseStock()
    await page.unrouteAll({ behavior: 'wait' })
  }
})

test('details retain reversal evidence and chart only effective consumption', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await openMaterials(page)
  await page.route('**/api/materials/101/consumptions?**', route => route.fulfill({
    json: {
      consumptions: [
        { id: 1, quantity: 2, status: 'active', created_at: '2026-11-01', order_no: 'ACTIVE' },
        { id: 2, quantity: 7, status: 'reversed', created_at: '2026-11-01', order_no: 'REVERSED', reversal_reason: '错录撤销' },
      ],
      total: 2,
    },
  }))
  await page.locator('.data-table tbody tr').filter({ hasText: '物料审计A' })
    .getByRole('button', { name: '详情', exact: true }).click()
  const modal = page.locator('.modal').filter({ hasText: '物料详情 — 物料审计A' })
  await expect(modal).toContainText('仅有效消耗')
  await expect(modal).toContainText('REVERSED')
  await expect(modal).toContainText('已撤销')
  await expect(modal).toContainText('错录撤销')
  await expect.poll(() => modal.locator('canvas').evaluate(canvas => (
    canvas._chart?.data.datasets[0].data
  ))).toEqual([2])
  expect(failures).toEqual([])
})
