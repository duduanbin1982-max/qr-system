import { expect, test } from '@playwright/test'

import { loginWorkerMobile, observeRuntimeFailures, openMobileCode } from './helpers.js'


test.use({ viewport: { width: 390, height: 844 } })

test('blocked mobile report opens required evaluation and restores the report', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginWorkerMobile(page)

  await expect(page.locator('#quality-pending-badge')).toHaveText('1')
  await page.evaluate(() => switchMode('manual'))
  await openMobileCode(page, 'E2E-QUALITY-GATE-ORDER')
  await expect(page.locator('#s-order')).toHaveClass(/active/)
  const blockedReport = page.waitForResponse(response => (
    response.url().endsWith('/api/mobile/report')
      && response.request().method() === 'POST'
      && response.status() === 409
  ))
  await page.locator('#btn-report').click()
  const blockedPayload = await (await blockedReport).json()
  expect(blockedPayload.code).toBe('quality_evaluation_required')
  await expect(page.locator('#s-quality-evaluation')).toHaveClass(/active/, { timeout: 10_000 })
  await expect(page.locator('.toast')).toContainText('未完成的必评任务')
  await expect(page.locator('.quality-task')).not.toContainText('E2E Previous Worker')
  await expect(page.locator('.quality-identity-note')).toContainText('隐藏被评价人员身份')
  await expect(page.locator('.quality-task')).toContainText('E2E Cutting')
  await page.locator('.quality-task select[data-dimension="appearance_quality"]').selectOption('4')
  await page.locator('.quality-task button[data-action="submit"]').click()
  await expect(page.locator('#s-order')).toHaveClass(/active/)
  await expect(page.locator('.toast')).toContainText('必评任务已完成')
  await expect(page.locator('#mode-manual')).toHaveClass(/active/)
  await expect(page.locator('#rpt-qty')).toHaveValue('1')
  await expect(page.locator('#btn-report')).toContainText('提交报工')

  const successfulReport = page.waitForResponse(response => (
    response.url().endsWith('/api/mobile/report')
      && response.request().method() === 'POST'
      && response.status() === 200
  ))
  await page.locator('#btn-report').click()
  await successfulReport
  expect(failures).toEqual([])
})

test('mobile scan reports permission and completed-workpiece errors in Chinese', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginWorkerMobile(page)

  await openMobileCode(page, 'E2E-FORBIDDEN-001')
  await expect(page.locator('.toast')).toContainText(/权限范围|无权限|无权/)

  await page.locator('#inp-code').fill('E2E-COMPLETE-001')
  await page.locator('#manual-row button').click()
  await expect(page.locator('.toast')).toContainText(/已完成|无需报工/)
  expect(failures).toEqual([])
})
