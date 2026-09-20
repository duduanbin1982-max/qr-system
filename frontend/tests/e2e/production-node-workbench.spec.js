import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


test('production node workbench remains viewport-fixed and responsive', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  let operationRequestCount = 0
  let capacityOrderRequestCount = 0
  const nodes = Array.from({ length: 25 }, (_, index) => ({
    id: index + 1,
    process_id: index < 10 ? 7 : 8,
    process_name: index < 10 ? '焊接' : '铆接',
    node_code: `NODE-${String(index + 1).padStart(2, '0')}`,
    node_name: `生产节点-${String(index + 1).padStart(2, '0')}`,
    status: 'active',
    capacity_mode: 'exclusive',
    calendar_id: 1,
    capacity_minutes: 540,
  }))
  await page.route(/\/api\/production-nodes(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ nodes }),
  }))
  await page.route(/\/api\/production-nodes\/\d+\/capabilities(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ capabilities: [{ id: 1 }, { id: 2 }] }),
  }))
  await page.route(/\/api\/production-nodes\/\d+\/calendar-overrides(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      overrides: [
        { id: 81, end_at: '2099-01-01T12:00:00', status: 'active' },
        { id: 82, end_at: '2099-01-02T12:00:00', status: 'cancelled' },
      ],
    }),
  }))
  await page.route(/\/api\/schedule\/operations(?:\?.*)?$/, route => {
    operationRequestCount += 1
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ operations: [] }),
    })
  })
  await page.route(/\/api\/schedule\/capacity-orders(?:\?.*)?$/, route => {
    capacityOrderRequestCount += 1
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ orders: [] }),
    })
  })
  await page.setViewportSize({ width: 1366, height: 768 })
  await loginAdmin(page)
  await openSidebarPage(page, '生产管理', '生产管理')
  const main = page.locator('.main-content')
  await main.locator('.tab-btn').filter({ hasText: '生产排程' }).click()
  await expect(main).toContainText('生产排程')
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))

  const trigger = page.getByRole('button', { name: /生产节点管理/ })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '生产节点管理' })
  await expect(dialog).toBeVisible()
  const summary = dialog.locator('[data-test="node-summary"]')
  await expect(summary).toContainText('NODE-01')
  await expect(summary).toContainText('540 分钟')
  await expect(summary).toContainText('2 条')
  await expect(summary).toContainText('1 条')

  const desktopBox = await dialog.boundingBox()
  expect(desktopBox.x).toBeGreaterThanOrEqual(0)
  expect(desktopBox.y).toBeGreaterThanOrEqual(0)
  expect(desktopBox.x + desktopBox.width).toBeLessThanOrEqual(1366)
  expect(desktopBox.y + desktopBox.height).toBeLessThanOrEqual(768)
  await expect(dialog.locator('.node-workbench__header')).toBeVisible()
  await expect(dialog.locator('.node-workbench__tabs')).toBeVisible()
  await expect(dialog.locator('.node-workbench__footer')).toBeVisible()
  await expect(dialog.locator('[data-test^="node-item-"]')).toHaveCount(25)
  await dialog.getByRole('searchbox', { name: '搜索生产节点' }).fill('NODE-25')
  await expect(dialog.locator('[data-test^="node-item-"]')).toHaveCount(1)

  const listTab = dialog.getByRole('tab', { name: '节点列表' })
  const editorTab = dialog.getByRole('tab', { name: '节点编辑' })
  const capabilityTab = dialog.getByRole('tab', { name: '能力限制' })
  await listTab.focus()
  await page.keyboard.press('ArrowRight')
  await expect(editorTab).toBeFocused()
  await expect(editorTab).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('End')
  await expect(capabilityTab).toBeFocused()
  await expect(capabilityTab).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Home')
  await expect(listTab).toBeFocused()
  await expect(listTab).toHaveAttribute('aria-selected', 'true')

  await page.setViewportSize({ width: 800, height: 844 })
  await expect(dialog).toHaveClass(/node-workbench/)
  await expect(dialog.getByLabel('选择生产节点')).toBeVisible()
  await expect(dialog.locator('.node-workbench__tabs')).toHaveCSS('overflow-x', 'auto')
  await editorTab.click()
  const editorFields = dialog.locator('[data-test="node-fields"]')
  const editorColumns = await editorFields.evaluate(element => getComputedStyle(element).gridTemplateColumns)
  expect(editorColumns.trim().split(/\s+/)).toHaveLength(1)

  const nodeName = dialog.locator('[data-test="node-name"]')
  await expect(nodeName).toHaveValue('生产节点-01')
  await nodeName.fill('应被放弃的节点名称')
  await page.keyboard.press('Escape')
  const discardDialog = dialog.getByRole('alertdialog', { name: '未保存更改' })
  await expect(discardDialog).toBeVisible()

  const operationRequestsBeforeDiscardClose = operationRequestCount
  const capacityOrderRequestsBeforeDiscardClose = capacityOrderRequestCount
  const discardOperationResponse = page.waitForResponse(
    response => /\/api\/schedule\/operations(?:\?.*)?$/.test(response.url()),
  )
  const discardCapacityOrderResponse = page.waitForResponse(
    response => /\/api\/schedule\/capacity-orders(?:\?.*)?$/.test(response.url()),
  )
  await discardDialog.getByRole('button', { name: '放弃更改' }).click()
  const [discardOperationResult, discardCapacityOrderResult] = await Promise.all([
    discardOperationResponse,
    discardCapacityOrderResponse,
  ])
  expect(discardOperationResult.status()).toBe(200)
  expect(discardCapacityOrderResult.status()).toBe(200)
  expect(operationRequestCount).toBe(operationRequestsBeforeDiscardClose + 1)
  expect(capacityOrderRequestCount).toBe(capacityOrderRequestsBeforeDiscardClose + 1)
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()

  await trigger.click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('tab', { name: '节点列表' })).toHaveAttribute('aria-selected', 'true')
  await dialog.getByRole('tab', { name: '节点编辑' }).click()
  await expect(dialog.locator('[data-test="node-name"]')).toHaveValue('生产节点-01')

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(dialog.getByLabel('选择生产节点')).toBeVisible()
  const mobileBox = await dialog.boundingBox()
  expect(Math.abs(mobileBox.width - 390)).toBeLessThanOrEqual(1)
  expect(Math.abs(mobileBox.height - 844)).toBeLessThanOrEqual(1)

  const firstFocus = dialog.locator('[data-test="workbench-first-focus"]')
  const lastFocus = dialog.locator('[data-test="workbench-last-focus"]')
  await expect(firstFocus).toBeVisible({ timeout: 5_000 })
  await expect(lastFocus).toBeVisible()

  await lastFocus.focus()
  await page.keyboard.press('Tab')
  await expect(firstFocus).toBeFocused()

  await firstFocus.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(lastFocus).toBeFocused()

  const operationRequestsBeforeClose = operationRequestCount
  const capacityOrderRequestsBeforeClose = capacityOrderRequestCount
  const operationResponse = page.waitForResponse(
    response => /\/api\/schedule\/operations(?:\?.*)?$/.test(response.url()),
  )
  const capacityOrderResponse = page.waitForResponse(
    response => /\/api\/schedule\/capacity-orders(?:\?.*)?$/.test(response.url()),
  )
  await firstFocus.click()
  const [operationResult, capacityOrderResult] = await Promise.all([
    operationResponse,
    capacityOrderResponse,
  ])

  expect(operationResult.status()).toBe(200)
  expect(capacityOrderResult.status()).toBe(200)
  expect(operationRequestCount).toBe(operationRequestsBeforeClose + 1)
  expect(capacityOrderRequestCount).toBe(capacityOrderRequestsBeforeClose + 1)
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
  expect(failures).toEqual([])
})
