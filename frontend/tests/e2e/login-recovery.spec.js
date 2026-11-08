import { test, expect } from '@playwright/test'
import { loginAdmin } from './helpers.js'

for (const scenario of [
  { name: 'recovers once from a static script buffer failure', error: 'net::ERR_NO_BUFFER_SPACE', failures: 1, succeeds: true, loads: 2 },
  { name: 'does not retry another static script error', error: 'net::ERR_FAILED', failures: 1, succeeds: false, loads: 1 },
  { name: 'stops after a second static script buffer failure', error: 'net::ERR_NO_BUFFER_SPACE', failures: 2, succeeds: false, loads: 2 },
]) {
  test(`administrator login ${scenario.name}`, async ({ page }) => {
    let scriptLoads = 0
    let loginPosts = 0
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/auth/login') loginPosts++
    })
    await page.route(/\/static\/assets\/main-[^/]+\.js$/, async route => {
      scriptLoads++
      if (scriptLoads > scenario.failures) return route.continue()
      const request = route.request()
      // Playwright's route.abort cannot emit Chromium's ERR_NO_BUFFER_SPACE.
      // Inject that event explicitly while aborting the real entry script.
      page.emit('requestfailed', {
        url: () => request.url(),
        resourceType: () => 'script',
        failure: () => ({ errorText: scenario.error }),
      })
      await route.abort('failed')
    })
    if (scenario.succeeds) {
      await loginAdmin(page)
      await expect(page.locator('.sidebar')).toBeVisible()
    } else {
      await expect(loginAdmin(page)).rejects.toThrow(/toBeVisible/)
    }
    expect(scriptLoads, 'entry script loads must respect the single reload limit').toBe(scenario.loads)
    expect(loginPosts, 'credentials must be submitted only after the login form loads').toBe(scenario.succeeds ? 1 : 0)
  })
}
