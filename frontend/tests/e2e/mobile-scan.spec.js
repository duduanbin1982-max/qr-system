import { expect, test } from '@playwright/test'

import { loginWorkerMobile, observeRuntimeFailures, openMobileCode } from './helpers.js'


test.use({ viewport: { width: 390, height: 844 } })

test('mobile quality evaluation center submits an upstream-process task', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginWorkerMobile(page)

  await expect(page.locator('#quality-pending-badge')).toHaveText('1')
  await page.locator('#quality-evaluation-entry').click()
  await expect(page.locator('#s-quality-evaluation')).toHaveClass(/active/)
  await expect(page.locator('.quality-task')).not.toContainText('E2E Previous Worker')
  await expect(page.locator('.quality-identity-note')).toContainText('隐藏被评价人员身份')
  await expect(page.locator('.quality-task')).toContainText('E2E Cutting')
  await page.locator('.quality-task select[data-dimension="appearance_quality"]').selectOption('4')
  await page.locator('.quality-task button[data-action="submit"]').click()
  await expect(page.locator('.toast')).toContainText('评价已提交')
  await expect(page.locator('.quality-task')).toHaveCount(0)
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
