import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'


const windowsVirtualenvPython = '.venv\\Scripts\\python.exe'
const pythonCommand = process.env.E2E_PYTHON || (
  process.platform === 'win32' && existsSync(windowsVirtualenvPython)
    ? windowsVirtualenvPython
    : process.platform === 'win32' ? 'python' : 'python3'
)
const e2ePort = process.env.E2E_PORT || '4173'
const e2eBaseURL = process.env.E2E_BASE_URL || `http://127.0.0.1:${e2ePort}`

export default defineConfig({
  testDir: './frontend/tests/e2e',
  outputDir: './test-results/playwright',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: e2eBaseURL,
    ignoreHTTPSErrors: true,
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: `${pythonCommand} scripts/e2e_server.py`,
    url: `${e2eBaseURL}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
