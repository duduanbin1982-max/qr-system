import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


function orderItems(count = 80) {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    product_name: `E2E 库存产品 ${index + 1}`,
    product_model: `E2E-INV-${String(index + 1).padStart(3, '0')}`,
    specification: index % 2 ? '标准' : '加厚',
    quantity: 10,
    available_quantity: 9,
    reserved: 1,
    frozen_quantity: 0,
    safe_stock: 2,
    location: index % 2 ? '东库' : '西库',
    unit: '件',
    order_no: `E2E-ORDER-${String(index + 1).padStart(3, '0')}`,
    customer: 'E2E Customer',
    is_low: 0,
  }))
}

function productGroups(count = 60) {
  return Array.from({ length: count }, (_, index) => ({
    product_id: index + 1,
    product_code: `E2E-PRODUCT-${String(index + 1).padStart(3, '0')}`,
    product_name: `E2E 产品 ${index + 1}`,
    specification: index % 2 ? '标准' : '加厚',
    quantity: 20,
    reserved_quantity: 2,
    frozen_quantity: 0,
    available_quantity: 18,
    order_count: 2,
    lot_count: 1,
    location_count: 1,
    product_alert_level: 'normal',
  }))
}

test('inventory desktop filter workbench is full-width, persistent, and uses a sticky header', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)

  await page.route(/\/api\/inventory\/capabilities(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ product_query_enabled: true }),
  }))
  await page.route(/\/api\/inventory\/filter-options(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      specifications: [
        { value: '标准', inventory_count: 40 },
        { value: '加厚', inventory_count: 40 },
      ],
      quality_statuses: [{ value: 'qualified', inventory_count: 80 }],
      locations: [
        { value: '东库', inventory_count: 40 },
        { value: '西库', inventory_count: 40 },
      ],
    }),
  }))
  await page.route(/\/api\/inventory\/stats(?:\?.*)?$/, async route => {
    const view = new URL(route.request().url()).searchParams.get('view')
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        total_items: view === 'product' ? 60 : 80,
        total_quantity: 800,
        total_value: 12500,
        low_stock: 0,
        today_in: 10,
        today_out: 4,
      }),
    })
  })
  await page.route(/\/api\/inventory(?:\/[^?]*)?(?:\?.*)?$/, route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === '/api/inventory/product-groups') {
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: productGroups(), total: 60, page: 1, limit: 200 }),
      })
    }
    if (pathname === '/api/inventory') {
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: orderItems(), total: 80, page: 1, limit: 100 }),
      })
    }
    return route.fallback()
  })

  await openSidebarPage(page, '库存管理', '库存管理')
  const main = page.locator('.main-content')
  const header = main.locator('.inventory-order-header')
  const workbench = header.locator('.inventory-filter-workbench')
  await expect(header).toBeVisible()
  await expect(workbench).toBeVisible()

  const headerBox = await header.boundingBox()
  const titleBox = await header.locator('h3').boundingBox()
  const workbenchBox = await workbench.boundingBox()
  expect(workbenchBox.y).toBeGreaterThan(titleBox.y + titleBox.height - 1)
  expect(workbenchBox.width).toBeGreaterThan(headerBox.width * 0.9)

  await workbench.locator('.inventory-spec-dropdown summary').click()
  await workbench.getByText('标准', { exact: true }).click()
  await workbench.locator('.inventory-spec-dropdown summary').click()
  await expect(workbench.getByText('规格：标准', { exact: false })).toBeVisible()

  await workbench.getByPlaceholder('例如：待出库-东库').fill('E2E 标准库存')
  await workbench.getByRole('button', { name: '保存当前条件', exact: true }).click()
  await expect(workbench.getByLabel('已保存筛选')).toContainText('E2E 标准库存')

  const scrollArea = main.locator('.inventory-table-scroll')
  const firstHeader = scrollArea.locator('thead th').first()
  expect(await firstHeader.evaluate(element => getComputedStyle(element).position)).toBe('sticky')
  const before = await firstHeader.boundingBox()
  await scrollArea.evaluate(element => { element.scrollTop = 600 })
  const after = await firstHeader.boundingBox()
  expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual(1)

  await main.getByRole('tab', { name: /按产品编码/ }).click()
  const productWorkbench = main.locator('.inventory-product-card .inventory-filter-workbench')
  await expect(productWorkbench).toBeVisible()
  await expect(productWorkbench.getByRole('button', { name: '导出当前筛选' })).toBeVisible()
  await expect(main.locator('.inventory-product-card .inventory-table-scroll thead')).toBeVisible()
  expect(failures).toEqual([])
})
