import { expect } from '@playwright/test'


export const TEST_PASSWORD = 'Test@1234'

export function observeRuntimeFailures(page) {
  const failures = []
  page.on('pageerror', error => failures.push(`pageerror: ${error.message}`))
  page.on('response', response => {
    if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`)
  })
  return failures
}

export async function loginAdmin(page) {
  await page.goto('/')
  await page.getByPlaceholder('请输入用户名').fill('e2eadmin')
  await page.getByPlaceholder('请输入密码').fill(TEST_PASSWORD)
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page.locator('.sidebar')).toBeVisible()
}

export async function loginWorkerMobile(page) {
  await page.goto('/mobile.html')
  await page.locator('#inp-user').fill('e2eworker')
  await page.locator('#inp-pwd').fill(TEST_PASSWORD)
  await page.locator('#btn-login').click()
  await expect(page.locator('#s-main')).toHaveClass(/active/)
}

export async function openSidebarPage(page, label, expectedText = label) {
  const sidebar = page.locator('.sidebar')
  const target = sidebar.getByText(label, { exact: true })
  if (!await target.isVisible()) {
    await target.evaluate(element => element.click())
  } else {
    await target.click()
  }
  const main = page.locator('.main-content')
  await expect(main).toContainText(expectedText, { timeout: 15_000 })
  await expect(main).not.toContainText('加载失败')
  await expect(main).not.toContainText('无页面访问权限')
}

export async function openMobileCode(page, code) {
  const manualButton = page.locator('.sub-btn').filter({ hasText: '手动输入' })
  await manualButton.click()
  await page.locator('#inp-code').fill(code)
  await page.locator('#manual-row button').click()
}
