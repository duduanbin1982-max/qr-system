import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'

const headers = ['员工姓名', '工号', '岗位', '报工时间', '订单号/序列号', '产品编码', '正常数量', '返修数量', '报废数量']
const firstWorker = { user_id: 1, worker_name: '张三,"班"\n成员', employee_no: '0012', position_name: '=焊接岗' }
const secondWorker = { user_id: 2, worker_name: '李四', employee_no: '0013', position_name: '@打磨岗' }
const normal = { id: 1, type: 'normal', quantity: 12.5, created_at: '2026-10-09 09:30:21', qr_mode: 'serial', order_id: 10, order_no: '26100901', serial_no: '26100901-0001', product_code: 'SB121,"加厚"\nA' }
const rework = { ...normal, id: 2, type: 'rework', quantity: 0.125, qr_mode: 'batch', order_no: '26100902', product_code: '+SB81' }
const scrap = { ...normal, id: 3, type: 'scrap', quantity: 2, serial_no: '', order_no: '26100903', product_code: 'SB50' }

// Read logical CSV rows, including quoted commas, escaped quotes and newlines.
function parseCsv(text) {
  const rows = []
  let row = [], cell = '', quoted = false
  const csv = text.replace(/^\uFEFF/, '')
  for (let index = 0; index < csv.length; index++) {
    const char = csv[index]
    if (char === '"') {
      if (quoted && csv[index + 1] === '"') { cell += '"'; index++ }
      else quoted = !quoted
    } else if (char === ',' && !quoted) {
      row.push(cell); cell = ''
    } else if (char === '\n' && !quoted) {
      row.push(cell); rows.push(row); row = []; cell = ''
    } else cell += char
  }
  if (cell.length || row.length) { row.push(cell); rows.push(row) }
  return rows
}

async function stubDaily(page, isTruncated = false) {
  await page.route(/\/api\/stats\/daily(?:\?.*)?$/, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        records: [normal, rework, scrap],
        employee_groups: [{ ...firstWorker, records: [normal, rework] }, { ...secondWorker, records: [scrap] }],
        summary: [{ id: 1, name: '焊接', record_count: 3, total_output: 12.5, total_rework: 0.125, total_scrap: 2 }],
        summary_totals: {}, work_time_summary: {}, is_truncated: isTruncated,
      }),
    })
  })
}

async function downloadDetail(page) {
  const pendingDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出明细', exact: true }).click()
  const download = await pendingDownload
  expect(await download.failure()).toBeNull()
  expect(download.suggestedFilename()).toMatch(/^日报表_员工明细_\d{4}-\d{2}-\d{2}\.csv$/)
  const bytes = await readFile(await download.path())
  expect([...bytes.subarray(0, 3)]).toEqual([0xEF, 0xBB, 0xBF])
  return parseCsv(bytes.toString('utf8'))
}

test('daily detail downloads nine safe CSV columns and inherits employee and type filters', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  await loginAdmin(page)
  await stubDaily(page)
  await openSidebarPage(page, '统计报表')
  await expect(page.getByRole('button', { name: '导出明细', exact: true })).toBeEnabled()

  const rows = await downloadDetail(page)
  expect(rows).toEqual([
    headers,
    [firstWorker.worker_name, '0012', "'=焊接岗", normal.created_at, '26100901-0001', normal.product_code, '12.5', '0', '0'],
    [firstWorker.worker_name, '0012', "'=焊接岗", normal.created_at, '26100902', "'+SB81", '0', '0.125', '0'],
    ['李四', '0013', "'@打磨岗", normal.created_at, '26100903', 'SB50', '0', '0', '2'],
  ])
  expect(rows.every(row => row.length === 9)).toBe(true)
  expect(rows.flat().join('|')).not.toContain('小计')

  await page.getByPlaceholder('搜索员工/工号/班组').fill('0012')
  await page.locator('.daily-detail-filters select').selectOption('rework')
  expect(await downloadDetail(page)).toEqual([headers, rows[2]])
  expect(failures).toEqual([])
})

test('daily detail refuses truncated CSV data even when the employee filter has one result', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const downloads = []
  page.on('download', download => downloads.push(download))
  await loginAdmin(page)
  await stubDaily(page, true)
  await openSidebarPage(page, '统计报表')
  await page.getByPlaceholder('搜索员工/工号/班组').fill('0013')
  await page.getByRole('button', { name: '导出明细', exact: true }).click()
  await expect(page.getByText('数据已截断，请缩小筛选范围后再导出明细', { exact: true })).toBeVisible()
  expect(downloads).toEqual([])
  expect(failures).toEqual([])
})
