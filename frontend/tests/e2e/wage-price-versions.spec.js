import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


const references = [
  { route_id: 1, route_name: 'E2E 车工路线', route_category: '机加工', process_id: 11, process_name: '车削', seq_order: 1 },
  { route_id: 1, route_name: 'E2E 车工路线', route_category: '机加工', process_id: 12, process_name: '钻孔', seq_order: 2 },
  { route_id: 2, route_name: 'E2E 铣工路线', route_category: '机加工', process_id: 21, process_name: '铣削', seq_order: 1 },
]

const versions = [
  {
    id: 101, route_id: 1, route_name: 'E2E 车工路线', process_id: 11, process_name: '车削',
    normal_unit_price_micros: 100000, rework_rate_basis_points: 5000, rework_rate_configured: 1,
    valid_from: '2026-01-01 07:00:00', valid_to: '', status: 'approved',
    created_by_name: 'E2E Preparer', approved_by_name: 'E2E Approver', row_version: 1,
  },
  {
    id: 102, route_id: 1, route_name: 'E2E 车工路线', process_id: 11, process_name: '车削',
    normal_unit_price_micros: 120000, rework_rate_basis_points: 6000, rework_rate_configured: 1,
    valid_from: '2099-09-01 07:00:00', valid_to: '', status: 'draft',
    created_by_name: 'E2E Preparer', created_at: '2026-08-09 09:30:00', remark: 'E2E 调价依据', row_version: 3,
  },
  {
    id: 201, route_id: 2, route_name: 'E2E 铣工路线', process_id: 21, process_name: '铣削',
    normal_unit_price_micros: 80000, rework_rate_basis_points: 0, rework_rate_configured: 0,
    valid_from: '2026-01-01 07:00:00', valid_to: '', status: 'approved',
    created_by_name: 'E2E Preparer', approved_by_name: 'E2E Approver', row_version: 1,
  },
]


test('price version workflow stays task-focused across desktop and mobile', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await page.route(/\/api\/route-price-versions\/reference(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ items: references }),
  }))
  await page.route(/\/api\/route-price-versions(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ versions }),
  }))

  await loginAdmin(page)
  await openSidebarPage(page, '工资核算', '工资批次台账')
  const main = page.locator('.main-content')
  await main.getByRole('button', { name: '工价版本', exact: true }).click()

  await expect(main.locator('.price-version-page')).toBeVisible()
  await expect(main.locator('[data-testid^="route-price-card-"]')).toHaveCount(2)
  await main.locator('[data-testid="route-price-card-2"] button').click()
  await expect(main.locator('.current-table tbody tr')).toHaveCount(1)
  await expect(main.locator('[data-testid="route-price-card-1"]')).toContainText('1 待处理')

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForTimeout(400)
  await page.screenshot({ path: 'test-results/price-version-current-desktop.png', fullPage: true })

  await main.locator('[data-testid="change-price-2-21"]').click()
  const modal = page.locator('.price-modal')
  await expect(modal).toBeVisible()
  await expect(modal).toContainText('¥8.0000')
  await page.waitForTimeout(400)
  await page.screenshot({ path: 'test-results/price-version-change-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(modal).toBeVisible()
  await page.waitForTimeout(400)
  const modalBox = await modal.boundingBox()
  expect(modalBox.x).toBeGreaterThanOrEqual(0)
  expect(modalBox.x + modalBox.width).toBeLessThanOrEqual(390)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: 'test-results/price-version-change-mobile.png', fullPage: true })
  expect(failures).toEqual([])
})
