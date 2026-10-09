import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DailyTab from '@/views/stats/DailyTab.vue'

const mocks = vi.hoisted(() => ({
  dailyStats: vi.fn(),
  exportCSV: vi.fn(),
  showToast: vi.fn(),
  can: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({ api: { domains: { stats: { dailyStats: mocks.dailyStats } } } }))
vi.mock('@/lib/auth.js', () => ({ can: mocks.can }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))
vi.mock('@/views/stats/shared.js', () => ({ exportCSV: mocks.exportCSV }))

const headers = ['员工姓名', '工号', '岗位', '报工时间', '订单号/序列号', '产品编码', '正常数量', '返修数量', '报废数量']
const group = {
  user_id: 1, worker_name: '张三', employee_no: '0012', position_name: '焊接岗',
  group_name: '一班', department_name: '生产部',
}
const record = {
  id: 1, user_id: 1, type: 'normal', quantity: 12.5, created_at: '2026-10-09 09:30:21',
  qr_mode: 'batch', order_id: 10, order_no: '26100901', product_code: 'SB121-001',
  product_name: '静音机头', product_model: 'SB121', product_spec: '加厚', customer: '客户',
  process_name: '焊接工序', route_name: '四片焊接路线', quality_result: '合格', remark: '备注',
}

function response(records = [record], options = {}) {
  return {
    records,
    employee_groups: [{ ...group, records }],
    summary: [{ id: 1, name: '焊接工序', record_count: 3, total_output: 12.5, total_scrap: 1, total_rework: 2 }],
    summary_totals: {}, work_time_summary: {}, is_truncated: false,
    ...options,
  }
}

const wrappers = []
async function mountDaily(data = response()) {
  mocks.dailyStats.mockResolvedValue(data)
  const wrapper = mount(DailyTab, { props: { date: '2026-10-09', productCode: 'SB121-001' } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

async function clickExport(wrapper, label = '导出明细') {
  await wrapper.findAll('button').find(button => button.text() === label).trigger('click')
}

describe('daily detail CSV export', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mocks.can.mockReturnValue(true)
  })
  afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

  it('exports exactly nine columns and one row per fact without subtotals or unrelated fields', async () => {
    const records = [record, { ...record, id: 2, type: 'rework', quantity: 2 }, { ...record, id: 3, type: 'scrap', quantity: 1 }]
    const wrapper = await mountDaily(response(records))
    await clickExport(wrapper)

    expect(mocks.exportCSV).toHaveBeenCalledExactlyOnceWith([
      headers,
      ['张三', '0012', '焊接岗', record.created_at, '26100901', 'SB121-001', 12.5, 0, 0],
      ['张三', '0012', '焊接岗', record.created_at, '26100901', 'SB121-001', 0, 2, 0],
      ['张三', '0012', '焊接岗', record.created_at, '26100901', 'SB121-001', 0, 0, 1],
    ], '日报表_员工明细_2026-10-09')
    const rows = mocks.exportCSV.mock.calls[0][0]
    expect(rows.every(row => row.length === 9)).toBe(true)
    expect(rows.flat().join('|')).not.toContain('小计')
    expect(wrapper.text()).toContain('客户')
    expect(wrapper.text()).toContain('张三 小计')
    expect(mocks.dailyStats).toHaveBeenCalledExactlyOnceWith({ date: '2026-10-09', per_page: 5000, product_code: 'SB121-001' })
  })

  it('uses a serial number only in serial mode and otherwise preserves the order display rule', async () => {
    const wrapper = await mountDaily(response([
      { ...record, qr_mode: 'serial', serial_no: '26100901-0001', display_order_no: '26100901-0001' },
      { ...record, id: 2, qr_mode: 'serial', serial_no: '', display_order_no: '26100901' },
      { ...record, id: 3, qr_mode: 'batch', serial_no: 'IGNORED', display_order_no: '26100902' },
    ]))
    await clickExport(wrapper)
    expect(mocks.exportCSV.mock.calls[0][0].slice(1).map(row => row[4])).toEqual(['26100901-0001', '26100901', '26100902'])
  })

  it('preserves zero and decimal quantities, defaults legacy empty types to normal and leaves missing fields blank', async () => {
    const records = [
      { ...record, quantity: 0, product_code: null, created_at: null },
      { ...record, id: 2, type: 'rework', quantity: 0.125 },
      { ...record, id: 3, type: 'scrap', quantity: '0.250' },
      { ...record, id: 4, type: '', quantity: 3 },
    ]
    const wrapper = await mountDaily(response(records, { employee_groups: [{ ...group, employee_no: null, position_name: null, records }] }))
    await clickExport(wrapper)
    const rows = mocks.exportCSV.mock.calls[0][0].slice(1)
    expect(rows[0]).toEqual(['张三', '', '', '', '26100901', '', 0, 0, 0])
    expect(rows.map(row => row.slice(6))).toEqual([[0, 0, 0], [0, 0.125, 0], [0, 0, '0.250'], [3, 0, 0]])
    expect(rows.every(row => row[2] === '')).toBe(true)
  })

  it('exports only records matching both employee and type filters', async () => {
    const rework = { ...record, id: 2, type: 'rework', quantity: 2 }
    const other = { ...record, id: 3, user_id: 2, type: 'rework', quantity: 4 }
    const wrapper = await mountDaily(response([record, rework, other], { employee_groups: [
      { ...group, records: [record, rework] },
      { ...group, user_id: 2, worker_name: '李四', employee_no: '0013', records: [other] },
    ] }))
    await wrapper.get('input[placeholder="搜索员工/工号/班组"]').setValue('0012')
    await wrapper.get('.daily-detail-filters select').setValue('rework')
    await clickExport(wrapper)
    expect(mocks.exportCSV).toHaveBeenCalledExactlyOnceWith([
      headers,
      ['张三', '0012', '焊接岗', record.created_at, '26100901', 'SB121-001', 0, 2, 0],
    ], '日报表_员工明细_2026-10-09')
  })

  it('exports the same data with older API responses that do not include employee groups', async () => {
    const wrapper = await mountDaily(response([{ ...record, ...group }], { employee_groups: [] }))
    await clickExport(wrapper)
    expect(mocks.exportCSV.mock.calls[0][0]).toEqual([
      headers, ['张三', '0012', '焊接岗', record.created_at, '26100901', 'SB121-001', 12.5, 0, 0],
    ])
  })

  it('blocks a truncated dataset even after local filtering leaves a small result', async () => {
    const wrapper = await mountDaily(response([record], { is_truncated: true }))
    await wrapper.get('input[placeholder="搜索员工/工号/班组"]').setValue('0012')
    await clickExport(wrapper)
    expect(mocks.exportCSV).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledExactlyOnceWith('数据已截断，请缩小筛选范围后再导出明细', 'warning')
  })

  it('does not export empty data and preserves the existing empty-data warning', async () => {
    const wrapper = await mountDaily(response([], { employee_groups: [], summary: [] }))
    wrapper.vm.exportDetailCsv()
    expect(mocks.exportCSV).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledExactlyOnceWith('没有数据可导出', 'warning')
  })

  it('keeps export actions hidden without stats:view permission', async () => {
    mocks.can.mockReturnValue(false)
    const wrapper = await mountDaily()
    expect(wrapper.find('.daily-actions').exists()).toBe(false)
    expect(mocks.exportCSV).not.toHaveBeenCalled()
  })

  it('does not change the process-summary CSV', async () => {
    const wrapper = await mountDaily()
    await clickExport(wrapper, '导出汇总')
    expect(mocks.exportCSV).toHaveBeenCalledExactlyOnceWith([
      ['工序', '报工次数', '产出', '报废', '返修'],
      ['焊接工序', 3, 12.5, 1, 2],
    ], '日报表_工序汇总_2026-10-09')
  })
})
