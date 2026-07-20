import { expect, test } from '@playwright/test'

import { loginWorkerMobile, observeRuntimeFailures, openMobileCode } from './helpers.js'


test.use({ viewport: { width: 390, height: 844 } })

test('mobile scan opens and submits the previous-process handoff review', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginWorkerMobile(page)
  await openMobileCode(page, 'E2E-HANDOFF-001')

  await expect(page.locator('#s-handoff')).toHaveClass(/active/)
  await expect(page.locator('#handoff-title')).toContainText('E2E Previous Worker')
  await page.locator('#handoff-stars button[data-score="4"]').click()
  await page.locator('#handoff-submit').click()
  await expect(page.locator('#s-order')).toHaveClass(/active/)
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
