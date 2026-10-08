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

test('inventory filters persist while the 200-row product table pins key columns across both scroll axes', async ({ page }) => {
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
        body: JSON.stringify({ items: productGroups(200), total: 450, page: 1, limit: 200 }),
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

  const productViewRenderStartedAt = await page.evaluate(() => performance.now())
  await main.getByRole('tab', { name: /按产品编码/ }).click()
  const productWorkbench = main.locator('.inventory-product-card .inventory-filter-workbench')
  await expect(productWorkbench).toBeVisible()
  await expect(productWorkbench.getByRole('button', { name: '导出当前筛选' })).toBeVisible()
  const productScroll = main.locator('.inventory-product-card .inventory-product-scroll')
  await expect(productScroll).toHaveAttribute('tabindex', '0')
  await expect(productScroll.locator('tbody tr')).toHaveCount(200)
  await expect(main.getByText('共 450 个产品，当前显示 1–200')).toBeVisible()
  const productViewRenderDuration = await page.evaluate(
    startedAt => performance.now() - startedAt,
    productViewRenderStartedAt,
  )
  expect(productViewRenderDuration).toBeLessThan(5000)

  const codeHeader = productScroll.locator('thead th.inventory-frozen--code')
  const nameHeader = productScroll.locator('thead th.inventory-frozen--name')
  const specHeader = productScroll.locator('thead th.inventory-frozen--spec')
  const scrollingHeader = productScroll.locator('thead th').nth(3)
  const codeCell = productScroll.locator('tbody td.inventory-frozen--code').first()
  const nameCell = productScroll.locator('tbody td.inventory-frozen--name').first()
  const specCell = productScroll.locator('tbody td.inventory-frozen--spec').first()
  for (const headerCell of [codeHeader, nameHeader, specHeader]) {
    await expect(headerCell).toHaveCSS('position', 'sticky')
  }
  expect(Number(await codeHeader.evaluate(element => getComputedStyle(element).zIndex))).toBeGreaterThan(
    Number(await scrollingHeader.evaluate(element => getComputedStyle(element).zIndex)),
  )

  const productBefore = {
    code: await codeHeader.boundingBox(),
    name: await nameHeader.boundingBox(),
    spec: await specHeader.boundingBox(),
    scrolling: await scrollingHeader.boundingBox(),
    codeCell: await codeCell.boundingBox(),
    nameCell: await nameCell.boundingBox(),
    specCell: await specCell.boundingBox(),
  }
  const offsets = await Promise.all([codeHeader, nameHeader, specHeader].map(element =>
    element.evaluate(node => Number.parseFloat(getComputedStyle(node).left)),
  ))
  expect(offsets[0]).toBe(0)
  expect(offsets[1]).toBeCloseTo(productBefore.code.width, 0)
  expect(offsets[2]).toBeCloseTo(productBefore.code.width + productBefore.name.width, 0)
  expect(await specHeader.evaluate(element => getComputedStyle(element).boxShadow)).not.toBe('none')
  await productScroll.evaluate(element => {
    element.scrollLeft = 600
    element.scrollTop = 500
  })
  await expect.poll(() => productScroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
  const productAfter = {
    code: await codeHeader.boundingBox(),
    name: await nameHeader.boundingBox(),
    spec: await specHeader.boundingBox(),
    scrolling: await scrollingHeader.boundingBox(),
    codeCell: await codeCell.boundingBox(),
    nameCell: await nameCell.boundingBox(),
    specCell: await specCell.boundingBox(),
  }
  for (const key of ['code', 'name', 'spec']) {
    expect(Math.abs(productAfter[key].x - productBefore[key].x)).toBeLessThanOrEqual(1)
    expect(Math.abs(productAfter[key].y - productBefore[key].y)).toBeLessThanOrEqual(1)
    expect(Math.abs(productAfter[`${key}Cell`].x - productBefore[`${key}Cell`].x)).toBeLessThanOrEqual(1)
  }
  expect(productAfter.scrolling.x).toBeLessThan(productBefore.scrolling.x)
  expect(Math.abs(productAfter.scrolling.y - productBefore.scrolling.y)).toBeLessThanOrEqual(1)
  expect(failures).toEqual([])
})

test('inventory summary cards switch data sources and low-stock clicks keep both views isolated', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)

  const orderSummary = { total_items: 12, total_quantity: 96, total_value: 12500, today_in: 10, today_out: 4, low_stock: 3 }
  const productSummary = { total_items: 7, total_quantity: 71, total_value: 7100, today_in: 0, today_out: 2, low_stock: 2 }
  const lowOrderSummary = { total_items: 3, total_quantity: 6, total_value: 120, today_in: 0, today_out: 1, low_stock: 3 }
  const lowProductSummary = { total_items: 2, total_quantity: 5, total_value: 100, today_in: 0, today_out: 0, low_stock: 2 }
  const requests = []
  await page.route(/\/api\/inventory(?:\/[^?]*)?(?:\?.*)?$/, async route => {
    const url = new URL(route.request().url())
    const params = Object.fromEntries(url.searchParams)
    const product = params.view === 'product'
    const low = params.low_stock === '1'
    let response
    if (url.pathname === '/api/inventory/capabilities') response = { product_query_enabled: true }
    else if (url.pathname === '/api/inventory/filter-options') response = { specifications: [], locations: [], quality_statuses: [] }
    else if (url.pathname === '/api/inventory/stats') response = low
      ? (product ? lowProductSummary : lowOrderSummary)
      : (product ? productSummary : orderSummary)
    else if (url.pathname === '/api/inventory/product-groups') response = { items: productGroups(low ? 2 : 7), total: low ? 2 : 7, page: 1, limit: 200 }
    else if (url.pathname === '/api/inventory') response = { items: orderItems(low ? 3 : 12), total: low ? 3 : 12, page: 1, limit: 100 }
    else return route.fallback()

    if (['/api/inventory', '/api/inventory/product-groups', '/api/inventory/stats'].includes(url.pathname)) {
      requests.push({ path: url.pathname, params })
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(response) })
  })

  await openSidebarPage(page, '库存管理', '库存管理')
  const main = page.locator('.main-content')
  const summaryBar = main.locator('.inventory-summary-bar')
  async function expectSummary(summary) {
    await expect(summaryBar.locator('.s-val')).toHaveText([
      String(summary.total_items), String(summary.total_quantity),
      Number(summary.total_value).toLocaleString('en-US'),
      String(summary.today_in), String(summary.today_out), String(summary.low_stock),
    ])
    await expect(summaryBar.getByRole('button')).toHaveAccessibleName(`筛选低库存，共 ${summary.low_stock} 项`)
  }
  await expectSummary(orderSummary)

  const orderStart = requests.length
  await summaryBar.getByRole('button', { name: '筛选低库存，共 3 项' }).click()
  const orderWorkbench = main.locator('.inventory-order-header .inventory-filter-workbench')
  await expect(orderWorkbench.getByRole('checkbox', { name: '仅低库存', exact: true })).toBeChecked()
  await expectSummary(lowOrderSummary)
  const orderRequests = requests.slice(orderStart)
  expect(orderRequests).toHaveLength(2)
  expect(orderRequests).toEqual(expect.arrayContaining([
    { path: '/api/inventory', params: expect.objectContaining({ low_stock: '1', page: '1' }) },
    { path: '/api/inventory/stats', params: expect.objectContaining({ low_stock: '1' }) },
  ]))
  expect(orderRequests.every(request => !('view' in request.params))).toBe(true)

  await main.getByRole('tab', { name: '按产品编码', exact: true }).click()
  const productWorkbench = main.locator('.inventory-product-card .inventory-filter-workbench')
  await expect(productWorkbench).toBeVisible()
  await expect(productWorkbench.getByRole('checkbox', { name: '仅低库存', exact: true })).not.toBeChecked()
  await expectSummary(productSummary)
  expect(await page.evaluate(() => localStorage.getItem('inventory-workbench:v1:view'))).toBe('product')

  const productStart = requests.length
  await summaryBar.getByRole('button', { name: '筛选低库存，共 2 项' }).click()
  await expect(productWorkbench.getByRole('checkbox', { name: '仅低库存', exact: true })).toBeChecked()
  await expectSummary(lowProductSummary)
  const productRequests = requests.slice(productStart)
  expect(productRequests).toHaveLength(2)
  expect(productRequests).toEqual(expect.arrayContaining([
    { path: '/api/inventory/product-groups', params: expect.objectContaining({ low_stock: '1', page: '1' }) },
    { path: '/api/inventory/stats', params: expect.objectContaining({ low_stock: '1', view: 'product' }) },
  ]))

  await main.getByRole('tab', { name: '按订单', exact: true }).click()
  await expect(orderWorkbench).toBeVisible()
  await expect(orderWorkbench.getByRole('checkbox', { name: '仅低库存', exact: true })).toBeChecked()
  await expectSummary(lowOrderSummary)
  expect(await page.evaluate(() => localStorage.getItem('inventory-workbench:v1:view'))).toBe('order')
  expect(failures).toEqual([])
})
