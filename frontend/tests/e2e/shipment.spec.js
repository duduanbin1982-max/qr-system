import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


test('shipment workflow creates, completes, and records payment for a real inventory item', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  page.on('dialog', dialog => dialog.accept())
  await loginAdmin(page)
  await openSidebarPage(page, '发货管理', '发货管理')

  const main = page.locator('.main-content')
  await main.getByRole('button', { name: /新建出库单/ }).click()
  const createModal = main.locator('.modal').filter({ hasText: '新建出库单' })
  await expect(createModal).toBeVisible()
  await createModal.locator('input[placeholder="客户名称"]').fill('E2E Shipment Customer')
  await createModal.locator('.shipment-items__header').getByRole('button', { name: /添加/ }).click()

  const itemRow = createModal.locator('.shipment-items__row').first()
  await itemRow.locator('input[placeholder*="型号"]').fill('E2E-SHIP-MODEL')
  await expect(itemRow.locator('.shipment-items__option')).toContainText('E2E Shipment Product')
  await itemRow.locator('.shipment-items__option').click()
  await itemRow.locator('input[type="number"]').fill('2')
  await createModal.locator('input[placeholder="0.00"]').fill('100')
  await createModal.getByRole('button', { name: '创建出库单', exact: true }).click()

  const shipmentRow = main.locator('.shipment-table tbody tr').first()
  await expect(shipmentRow).toContainText(/SH\d{8}-\d{3}/)
  await expect(shipmentRow).toContainText('待出库')

  await shipmentRow.getByRole('button', { name: /完成/ }).click()
  await expect(shipmentRow).toContainText('已出库')

  await shipmentRow.getByRole('button', { name: /收款/ }).click()
  const paymentModal = main.locator('.modal').filter({ hasText: '收款' })
  await expect(paymentModal).toBeVisible()
  await paymentModal.locator('select').selectOption({ label: '转账' })
  await paymentModal.getByRole('button', { name: '确认收款', exact: true }).click()
  await expect(shipmentRow).toContainText('已收清')
  expect(failures).toEqual([])
})
