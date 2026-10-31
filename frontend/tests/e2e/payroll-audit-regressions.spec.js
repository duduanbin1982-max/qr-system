import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'

test.use({ timezoneId: 'Asia/Shanghai' })

async function json(route, body) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function restoreWageTab(page, tab) {
  await page.addInitScript(value => localStorage.setItem('wageActiveTab', value), tab)
}

test('restored process analysis loads once and an empty month remains selectable', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const months = []
  await restoreWageTab(page, 'process')
  await page.route('**/api/wages/process-summary?**', route => {
    const month = new URL(route.request().url()).searchParams.get('year_month')
    months.push(month)
    return json(route, month === '2026-08'
      ? {
          summary: [{
            process_id: 7,
            process_name: '历史精车',
            worker_count: 1,
            total_quantity: 3,
            total_wage: 30,
          }],
          grand_total_wage: 30,
        }
      : { summary: [], grand_total_wage: 0 })
  })
  await page.route('**/api/route-price-versions/reference', route => json(route, {
    items: [{
      route_version_id: 81,
      route_name: '回归路线',
      route_category: '机加工',
      process_version_id: 71,
      process_name: '精车',
    }],
  }))
  await page.route('**/api/route-price-versions', route => json(route, {
    versions: [{
      id: 101,
      route_version_id: 81,
      process_version_id: 71,
      normal_unit_price_micros: 100000,
      status: 'approved',
    }],
  }))

  await loginAdmin(page)
  await openSidebarPage(page, '工资核算', '暂无工序分析数据')
  const main = page.locator('.main-content')
  const month = page.getByLabel('工序分析月份')
  await expect(month).toBeVisible()
  await expect(main.locator('.coverage-table')).toContainText('¥10.0000')
  expect(months).toHaveLength(1)

  await month.fill('2026-08')
  await month.press('Tab')
  await expect(main.locator('.distribution-list')).toContainText('历史精车')
  await expect(main.locator('.distribution-list')).toContainText('¥30.00')
  await expect(month).toHaveValue('2026-08')
  expect(months).toHaveLength(2)
  expect(months[1]).toBe('2026-08')
  expect(failures).toEqual([])
})

test('piecework filters return a paginated estimate to page one', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const queries = []
  await restoreWageTab(page, 'piece')
  await page.route('**/api/wages?**', route => {
    const query = Object.fromEntries(new URL(route.request().url()).searchParams)
    queries.push(query)
    return json(route, {
      wages: [{
        employee_id: Number(query.page),
        employee_name: `预估第${query.page}页员工`,
        employee_no: 'E2E-PAYROLL',
        total_quantity: 1,
        total_wage: 10,
        details: [],
      }],
      total: 101,
      page: Number(query.page),
      limit: 50,
    })
  })

  await loginAdmin(page)
  await openSidebarPage(page, '工资核算', '实时工资预估')
  const main = page.locator('.main-content')
  await expect(main).toContainText('预估第1页员工')
  await main.getByRole('button', { name: '下一页 ▶' }).click()
  await expect(main).toContainText('预估第2页员工')

  await main.getByLabel('含返工').check()
  await expect(main).toContainText('预估第1页员工')
  expect(queries.at(-1)).toMatchObject({ page: '1', include_rework: '1' })
  await main.getByRole('button', { name: '下一页 ▶' }).click()
  await expect(main).toContainText('预估第2页员工')

  const start = page.getByLabel('预估开始日期')
  await start.fill('2026-09-01')
  await start.press('Tab')
  await expect(main).toContainText('预估第1页员工')
  expect(queries.at(-1)).toMatchObject({
    page: '1',
    include_rework: '1',
    date_from: '2026-09-01',
  })
  expect(queries.every(query => /^[1-9]\d*$/.test(query.page))).toBe(true)
  expect(failures).toEqual([])
})

for (const scenario of [
  { name: 'October', instant: '2026-10-30T16:30:00Z', previous: '2026-09', current: '2026-10' },
  { name: 'January', instant: '2026-12-31T16:30:00Z', previous: '2026-12', current: '2027-01' },
]) {
  test(`comparison defaults use local months in Shanghai during ${scenario.name}`, async ({ page }) => {
    const failures = observeRuntimeFailures(page)
    const months = []
    await page.clock.setFixedTime(new Date(scenario.instant))
    await restoreWageTab(page, 'compare')
    await page.route('**/api/wages/monthly-summary?**', route => {
      months.push(new URL(route.request().url()).searchParams.get('year_month'))
      return json(route, {
        summary: [{ employee_name: '月份核对员工', total_wage: 10 }],
        grand_total_wage: 10,
      })
    })

    await loginAdmin(page)
    await openSidebarPage(page, '工资核算', '工资对比')
    const main = page.locator('.main-content')
    const inputs = main.locator('input[type="month"]')
    await expect(inputs.nth(0)).toHaveValue(scenario.previous)
    await expect(inputs.nth(1)).toHaveValue(scenario.current)
    await main.getByRole('button', { name: '对比', exact: true }).click()
    await expect(main).toContainText('月份核对员工')
    expect(months).toContain(scenario.previous)
    expect(months).toContain(scenario.current)
    expect(failures).toEqual([])
  })
}
