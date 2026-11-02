import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


async function openCustomers(page) {
  await openSidebarPage(page, '生产管理', '订单管理')
  await page.locator('.tab-btn').filter({ hasText: '客户管理' }).click()
  await expect(page.getByPlaceholder('搜索名称/联系人/电话...')).toBeVisible()
}

function customerList(name, total, withContact = 0) {
  return {
    customers: [{ id: 1, name, tags: 'VIP' }],
    total,
    summary: { total, with_orders: 0, with_contact: withContact, with_email: 0 },
    available_tags: ['VIP', '重点'],
  }
}

test('latest Enter search and tag selection survive an older customer response', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  let releaseOlder
  let olderResponse
  const olderGate = new Promise(resolve => { releaseOlder = resolve })
  await page.route('**/api/customers?**', async route => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('keyword') === 'Older') {
      await olderGate
      await route.fulfill({ json: customerList('Older customer', 35) })
    } else if (params.get('tag') === 'VIP') {
      await route.fulfill({ json: customerList('Latest VIP customer', 3, 2) })
    } else if (params.get('keyword') === 'Newest') {
      await route.fulfill({ json: customerList('Newest customer', 8, 5) })
    } else {
      await route.fulfill({ json: customerList('Initial customer', 1) })
    }
  })

  try {
    await openCustomers(page)
    await expect(page.locator('.data-table:visible')).toContainText('Initial customer')
    const search = page.getByPlaceholder('搜索名称/联系人/电话...')
    const olderStarted = page.waitForRequest(request => {
      const url = new URL(request.url())
      return url.pathname === '/api/customers' && url.searchParams.get('keyword') === 'Older'
    })
    await search.fill('Older')
    await search.press('Enter')
    await olderStarted
    await search.fill('Newest')
    await search.press('Enter')
    await expect(page.locator('.data-table:visible')).toContainText('Newest customer')
    await page.locator('.card-header select:visible').selectOption('VIP')
    await expect(page.locator('.data-table:visible')).toContainText('Latest VIP customer')
    olderResponse = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/customers' && url.searchParams.get('keyword') === 'Older'
    })
  } finally {
    releaseOlder()
    await page.unrouteAll({ behavior: 'wait' })
  }

  await (await olderResponse).finished()
  await page.evaluate(() => new Promise(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(resolve))
  }))
  await expect(page.locator('.data-table:visible')).toContainText('Latest VIP customer')
  await expect(page.locator('.data-table:visible')).not.toContainText('Older customer')
  await expect(page.getByPlaceholder('搜索名称/联系人/电话...')).toHaveValue('Newest')
  await expect(page.locator('.card-header select:visible')).toHaveValue('VIP')
  await expect(page.locator('.summary-item').filter({ hasText: '客户总数' }).locator('.s-val')).toHaveText('3')
  await expect(page.locator('.summary-item').filter({ hasText: '有联系人' }).locator('.s-val')).toHaveText('2')
  expect(failures).toEqual([])
})

test('deleting the only customer on page two returns to twenty persisted customers on page one', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  // These writes go to the disposable E2E database started by e2e_server.py.
  // APIRequestContext does not send Secure cookies over the HTTP test server.
  const session = (await page.context().cookies()).find(cookie => cookie.name === 'qr_token')
  expect(session).toBeDefined()
  const headers = { Authorization: `Bearer ${session.value}` }
  const prefix = 'E2E-Customer-Last-Page-'
  for (let index = 1; index <= 21; index++) {
    const response = await page.request.post('/api/customers', {
      headers,
      data: { name: `${prefix}${String(index).padStart(2, '0')}` },
    })
    expect(response.status(), await response.text()).toBe(200)
  }
  await openCustomers(page)
  const search = page.getByPlaceholder('搜索名称/联系人/电话...')
  await search.fill(prefix)
  await search.press('Enter')
  await expect(page.locator('.main-content')).toContainText('第 1 / 2 页（共 21 条）')
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.locator('.main-content')).toContainText('第 2 / 2 页（共 21 条）')
  const lastRow = page.locator('.data-table:visible tbody tr')
  await expect(lastRow).toHaveCount(1)
  const deletedName = await lastRow.getByTestId('customer-order-link').innerText()
  let deletions = 0
  page.on('request', request => {
    if (request.method() === 'DELETE' && new URL(request.url()).pathname.startsWith('/api/customers/')) {
      deletions++
    }
  })
  page.once('dialog', dialog => dialog.accept())
  await lastRow.locator('[title="删除"]').click()

  await expect(page.locator('.data-table:visible tbody tr')).toHaveCount(20)
  await expect(page.locator('.data-table:visible tbody tr').first().locator('.row-num')).toHaveText('1')
  await expect(page.locator('.data-table:visible')).not.toContainText(deletedName)
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
  await expect(page.locator('.summary-item').filter({ hasText: '客户总数' }).locator('.s-val')).toHaveText('20')
  expect(deletions).toBe(1)

  // A fresh API read verifies deletion persisted; a UI reload still starts on a valid page.
  const response = await page.request.get('/api/customers', {
    headers,
    params: { keyword: prefix, limit: 100 },
  })
  expect(response.status()).toBe(200)
  const persisted = await response.json()
  expect(persisted.total).toBe(20)
  expect(persisted.customers.map(customer => customer.name)).not.toContain(deletedName)
  await page.reload()
  await expect(page.getByPlaceholder('搜索名称/联系人/电话...')).toBeVisible()
  await page.getByPlaceholder('搜索名称/联系人/电话...').fill(prefix)
  await page.getByPlaceholder('搜索名称/联系人/电话...').press('Enter')
  await expect(page.locator('.data-table:visible tbody tr')).toHaveCount(20)
  await expect(page.locator('.data-table:visible tbody tr').first().locator('.row-num')).toHaveText('1')
  expect(failures).toEqual([])
})
