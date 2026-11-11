import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listWages: vi.fn(),
  getMonthlySummary: vi.fn(),
  downloadCSV: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { wages: {
    listWages: mocks.listWages,
    getMonthlySummary: mocks.getMonthlySummary,
  } } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))
vi.mock('@/composables/reports/reportSupport.js', () => ({ exportCSV: mocks.downloadCSV }))

import {
  buildMonthlyCsvRows,
  buildPayslipHtml,
  buildPieceworkCsvRows,
  collectAllPages,
} from '@/composables/wage/wageExport.js'
import { useWage } from '@/composables/useWage.js'

const Harness = defineComponent({
  setup: () => useWage(),
  template: '<div />',
})

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  mocks.listWages.mockResolvedValue({ wages: [], total: 0 })
  mocks.getMonthlySummary.mockResolvedValue({
    summary: [], total: 0, grand_total_quantity: 0, grand_total_wage: 0,
  })
})


describe('buildPieceworkCsvRows', () => {
  const fmtDate = value => String(value || '').slice(0, 10)
  const fmtMoney = value => Number(value || 0).toFixed(2)

  it('includes product code in detail rows and keeps subtotal columns aligned', () => {
    const rows = buildPieceworkCsvRows([
      {
        employee_name: '张三',
        position_name: '车工',
        employee_no: '1001',
        total_quantity: 2,
        total_wage: 10.5,
        details: [{
          date: '2026-09-02 08:00:00',
          order_no: '26090201',
          product_name: '静音外壳',
          product_code: 'P-195',
          process_name: '焊接',
          quantity: 2,
          unit_price: 5.25,
          wage: 10.5,
        }],
      },
    ], fmtDate, fmtMoney)

    expect(rows[0]).toEqual(['姓名', '岗位', '工号', '日期', '订单号', '产品', '产品编码', '工序', '数量', '单价', '工资'])
    expect(rows[1]).toEqual(['张三', '车工', '1001', '2026-09-02', '26090201', '静音外壳', 'P-195', '焊接', 2, '5.25', '10.50'])
    expect(rows[2]).toEqual(['张三', '车工', '1001', '', '', '', '', '小计', 2, '', '10.50'])
    expect(rows[3]).toEqual(['', '', '', '', '', '', '', '合计', 2, '', '10.50'])
  })

  it('exports an empty product code when legacy detail has none', () => {
    const rows = buildPieceworkCsvRows([
      { employee_name: '李四', total_quantity: 0, total_wage: 0, details: [{ product_name: '旧产品' }] },
    ], fmtDate, fmtMoney)

    expect(rows[1][6]).toBe('')
  })
})

describe('wage export risk closure', () => {
  const fmtMoney = value => Number(value || 0).toFixed(2)

  it('escapes payroll slip fields before writing the print document', () => {
    const attack = '</td><script>alert(1)</script>'
    const html = buildPayslipHtml({
      employee_name: attack,
      employee_no: '" onmouseover="alert(2)',
      position_name: 'A&B',
      total_quantity: 1,
      total_wage: 2,
    }, '2026-11<svg/onload=alert(3)>', fmtMoney)

    expect(html).not.toContain(attack)
    expect(html).not.toContain('<svg/onload=alert(3)>')
    expect(html).toContain('&lt;/td&gt;&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(html).toContain('&quot; onmouseover=&quot;alert(2)')
    expect(html).toContain('A&amp;B')
  })

  it('collects every stable page and rejects a changing export result', async () => {
    const fetchPage = vi.fn()
      .mockResolvedValueOnce({ items: [{ id: 1 }, { id: 2 }], total: 3 })
      .mockResolvedValueOnce({ items: [{ id: 3 }], total: 3 })

    await expect(collectAllPages(fetchPage, 'items', 2)).resolves.toMatchObject({
      items: [{ id: 1 }, { id: 2 }, { id: 3 }], total: 3,
    })
    expect(fetchPage).toHaveBeenNthCalledWith(2, 2, 2)

    await expect(collectAllPages(vi.fn()
      .mockResolvedValueOnce({ items: [{ id: 1 }], total: 2 })
      .mockResolvedValueOnce({ items: [{ id: 2 }], total: 3 }), 'items', 1))
      .rejects.toThrow('导出期间数据发生变化')
  })

  it('exports all piecework pages with the active filters without changing the visible page', async () => {
    const totalRows = 1001
    mocks.listWages.mockImplementation(params => {
      const start = (params.page - 1) * params.limit
      const end = Math.min(start + params.limit, totalRows)
      return Promise.resolve({
        wages: Array.from({ length: Math.max(end - start, 0) }, (_, offset) => {
          const employeeId = start + offset + 1
          return {
            employee_id: employeeId,
            employee_name: employeeId === totalRows ? '=FORMULA' : `员工${employeeId}`,
            employee_no: employeeId === totalRows ? '@CMD' : `E${employeeId}`,
            total_quantity: 1, total_wage: 1, details: [],
          }
        }),
        total: totalRows,
      })
    })
    const wrapper = mount(Harness)
    await flushPromises()
    const vm = wrapper.vm
    vm.page = 2
    vm.dateFrom = '2026-11-01'
    vm.dateTo = '2026-11-30'
    vm.includeRework = true
    vm.hideZero = true

    await vm.exportCSV()

    expect(vm.page).toBe(2)
    expect(mocks.listWages).toHaveBeenCalledWith({
      page: 1, limit: 1000, date_from: '2026-11-01', date_to: '2026-11-30',
      include_rework: '1', hide_zero: '1',
    })
    expect(mocks.listWages).toHaveBeenCalledWith({
      page: 2, limit: 1000, date_from: '2026-11-01', date_to: '2026-11-30',
      include_rework: '1', hide_zero: '1',
    })
    expect(mocks.downloadCSV).toHaveBeenCalledOnce()
    expect(mocks.downloadCSV.mock.calls[0][0]).toHaveLength(1003)
    expect(mocks.downloadCSV.mock.calls[0][1]).toBe('工资明细_2026-11-01_2026-11-30')
    wrapper.unmount()
  })

  it('freezes piecework export filters while later pages are loading', async () => {
    localStorage.setItem('wageActiveTab', 'piece')
    const wrapper = mount(Harness)
    await flushPromises()
    let resolveFirstPage
    const firstPage = new Promise(resolve => { resolveFirstPage = resolve })
    mocks.listWages.mockReset()
    mocks.listWages.mockImplementationOnce(() => firstPage)
      .mockResolvedValueOnce({
        wages: [{ employee_name: '第二页', total_quantity: 1, total_wage: 1, details: [] }],
        total: 1001,
      })
    const vm = wrapper.vm
    vm.dateFrom = '2026-11-01'
    vm.dateTo = '2026-11-30'
    vm.includeRework = true
    vm.hideZero = true

    const exportPromise = vm.exportCSV()
    vm.dateFrom = '2026-12-01'
    vm.dateTo = '2026-12-31'
    vm.includeRework = false
    vm.hideZero = false
    resolveFirstPage({
      wages: Array.from({ length: 1000 }, (_, index) => ({
        employee_name: `第一页${index + 1}`,
        total_quantity: 1,
        total_wage: 1,
        details: [],
      })),
      total: 1001,
    })
    await exportPromise

    expect(mocks.listWages).toHaveBeenNthCalledWith(2, {
      page: 2, limit: 1000, date_from: '2026-11-01', date_to: '2026-11-30',
      include_rework: '1', hide_zero: '1',
    })
    expect(mocks.downloadCSV.mock.calls[0][1]).toBe('工资明细_2026-11-01_2026-11-30')
    wrapper.unmount()
  })

  it('exports the full monthly summary with global ranks and aligned totals', async () => {
    const totalRows = 501
    mocks.getMonthlySummary.mockImplementation(params => {
      const start = (params.page - 1) * params.limit
      const end = Math.min(start + params.limit, totalRows)
      return Promise.resolve({
        summary: Array.from({ length: Math.max(end - start, 0) }, (_, offset) => {
          const employeeId = start + offset + 1
          return {
            user_id: employeeId,
            employee_name: employeeId === totalRows ? '末页员工' : `员工${employeeId}`,
            employee_no: `E${employeeId}`, total_quantity: 1, total_wage: 1,
          }
        }),
        total: totalRows, grand_total_quantity: totalRows, grand_total_wage: totalRows,
      })
    })
    localStorage.setItem('wageActiveTab', 'piece')
    const wrapper = mount(Harness)
    await flushPromises()
    const vm = wrapper.vm
    vm.monthlyPage = 4
    vm.monthlyMonth = '2026-10'

    await vm.exportMonthlyCSV()

    expect(vm.monthlyPage).toBe(4)
    expect(mocks.getMonthlySummary).toHaveBeenCalledWith({ year_month: '2026-10', page: 2, limit: 500 })
    const rows = mocks.downloadCSV.mock.calls[0][0]
    expect(rows).toHaveLength(503)
    expect(rows[501][0]).toBe(501)
    expect(rows[502]).toEqual(['', '', '合计', 501, '501.00', '100.0%'])
    expect(mocks.downloadCSV.mock.calls[0][1]).toBe('月度汇总_2026-10')
    wrapper.unmount()
  })

  it('freezes the monthly export month while later pages are loading', async () => {
    localStorage.setItem('wageActiveTab', 'monthly')
    const wrapper = mount(Harness)
    await flushPromises()
    let resolveFirstPage
    const firstPage = new Promise(resolve => { resolveFirstPage = resolve })
    mocks.getMonthlySummary.mockReset()
    mocks.getMonthlySummary.mockImplementationOnce(() => firstPage)
      .mockResolvedValueOnce({
        summary: [{ employee_name: '第二页', employee_no: 'E501', total_quantity: 1, total_wage: 1 }],
        total: 501, grand_total_quantity: 501, grand_total_wage: 501,
      })
    const vm = wrapper.vm
    vm.monthlyMonth = '2026-10'

    const exportPromise = vm.exportMonthlyCSV()
    vm.monthlyMonth = '2026-11'
    resolveFirstPage({
      summary: Array.from({ length: 500 }, (_, index) => ({
        employee_name: `第一页${index + 1}`,
        employee_no: `E${index + 1}`,
        total_quantity: 1,
        total_wage: 1,
      })),
      total: 501, grand_total_quantity: 501, grand_total_wage: 501,
    })
    await exportPromise

    expect(mocks.getMonthlySummary).toHaveBeenNthCalledWith(2, {
      year_month: '2026-10', page: 2, limit: 500,
    })
    expect(mocks.downloadCSV.mock.calls[0][1]).toBe('月度汇总_2026-10')
    wrapper.unmount()
  })

  it('builds monthly rows independently of the visible page', () => {
    expect(buildMonthlyCsvRows([
      { employee_name: '张三', employee_no: 'E1', total_quantity: 2, total_wage: 25 },
    ], { grand_total_quantity: 2, grand_total_wage: 25 }, fmtMoney)).toEqual([
      ['排名', '姓名', '工号', '总件数', '总工资', '占比'],
      [1, '张三', 'E1', 2, '25.00', '100.0%'],
      ['', '', '合计', 2, '25.00', '100.0%'],
    ])
  })
})
