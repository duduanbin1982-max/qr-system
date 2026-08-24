import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


const references = [
  {
    reference_key: '81:111', route_id: 1, route_version_id: 81, route_version: 2,
    route_name: 'E2E 车工路线', route_category: '机加工',
    route_version_status: 'published', route_content_digest: 'route-81',
    process_id: 11, process_version_id: 111, process_version: 3,
    process_name: '车削', process_version_status: 'published',
    process_content_digest: 'process-111', seq_order: 1,
    pricing_mode: 'published_adjustment',
  },
  {
    reference_key: '81:112', route_id: 1, route_version_id: 81, route_version: 2,
    route_name: 'E2E 车工路线', route_category: '机加工',
    route_version_status: 'published', route_content_digest: 'route-81',
    process_id: 12, process_version_id: 112, process_version: 1,
    process_name: '钻孔', process_version_status: 'published',
    process_content_digest: 'process-112', seq_order: 2,
    pricing_mode: 'published_adjustment',
  },
  {
    reference_key: '82:121', route_id: 2, route_version_id: 82, route_version: 1,
    route_name: 'E2E 铣工路线', route_category: '机加工',
    route_version_status: 'published', route_content_digest: 'route-82',
    process_id: 21, process_version_id: 121, process_version: 1,
    process_name: '铣削', process_version_status: 'published',
    process_content_digest: 'process-121', seq_order: 1,
    pricing_mode: 'published_adjustment',
  },
]

const versions = [
  {
    id: 101, route_id: 1, route_version_id: 81, route_name: 'E2E 车工路线',
    process_id: 11, process_version_id: 111, process_name: '车削',
    normal_unit_price_micros: 100000, rework_rate_basis_points: 5000,
    rework_rate_configured: 1, valid_from: '2026-01-01 07:00:00',
    valid_to: '', status: 'approved', row_version: 1,
  },
  {
    id: 102, route_id: 1, route_version_id: 81, route_name: 'E2E 车工路线',
    process_id: 11, process_version_id: 111, process_name: '车削',
    normal_unit_price_micros: 120000, rework_rate_basis_points: 6000,
    rework_rate_configured: 1, valid_from: '2099-09-01 07:00:00',
    valid_to: '', status: 'draft', created_by_name: 'E2E Preparer',
    remark: 'E2E 调价依据', row_version: 3,
  },
  {
    id: 201, route_id: 2, route_version_id: 82, route_name: 'E2E 铣工路线',
    process_id: 21, process_version_id: 121, process_name: '铣削',
    normal_unit_price_micros: 80000, rework_rate_basis_points: 0,
    rework_rate_configured: 0, valid_from: '2026-01-01 07:00:00',
    valid_to: '', status: 'approved', row_version: 1,
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
  await expect(main.locator('.route-version-group')).toHaveCount(2)
  await expect(main.locator('[data-testid^="reference-row-"]')).toHaveCount(3)
  await expect(main.locator('[data-testid="edit-price-102"]')).toBeVisible()

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForTimeout(400)
  await page.screenshot({ path: 'test-results/price-version-current-desktop.png', fullPage: true })

  await main.locator('[data-testid="create-price-82:121"]').click()
  const editor = page.locator('.price-editor')
  await expect(editor).toBeVisible()
  await expect(editor).toContainText('¥8.0000')
  await page.waitForTimeout(400)
  await page.screenshot({ path: 'test-results/price-version-change-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(editor).toBeVisible()
  await page.waitForTimeout(400)
  const editorBox = await editor.boundingBox()
  expect(editorBox.x).toBeGreaterThanOrEqual(0)
  expect(editorBox.x + editorBox.width).toBeLessThanOrEqual(390)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: 'test-results/price-version-change-mobile.png', fullPage: true })
  expect(failures).toEqual([])
})
