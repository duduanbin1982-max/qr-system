import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { hasPermission } from '@/lib/permissions.js'
import WageList from '@/views/WageList.vue'
import PayrollLedgerTab from '@/views/wage/PayrollLedgerTab.vue'
import PriceVersionEditor from '@/components/wage/PriceVersionEditor.vue'

const mocks = vi.hoisted(() => ({
  permissions: [],
  wages: {},
  router: { params: {} },
  toast: vi.fn(),
}))
vi.mock('@/lib/api.js', () => ({ api: { domains: { wages: mocks.wages } } }))
vi.mock('@/lib/auth.js', () => ({
  can: permission => hasPermission({ permissions: mocks.permissions }, permission),
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))
vi.mock('@/lib/router.js', () => ({ router: mocks.router }))

const wrappers = []
function render(component, options) {
  const wrapper = mount(component, options)
  wrappers.push(wrapper)
  return wrapper
}
function button(wrapper, label) {
  return wrapper.findAll('button').find(item => item.text() === label)
}
function state(wrapper) { return wrapper.vm.$.setupState }
function batch(overrides = {}) {
  return {
    id: 8, payroll_month: '2026-09', version: 1, row_version: 3,
    status: 'draft', legacy_imported: false, input_changed: false,
    exception_count: 0, priced_record_count: 1, source_record_count: 1,
    payable_wage_cents: 1000, ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  mocks.permissions = ['wages:view_all']
  mocks.router.params = {}
  mocks.toast.mockReset()
  const responses = {
    listWages: { wages: [], total: 0 },
    getMonthlySummary: { summary: [], total: 0, grand_total_wage: 0 },
    getProcessSummary: { summary: [], grand_total_wage: 0 },
    getWageTrends: [],
    getPositionSummary: { summary: [], grand_total_wage: 0 },
    getWagePrediction: {},
    getRoutePriceVersionReference: { items: [] },
    listRoutePriceVersions: { versions: [] },
    listPayrollBatches: { batches: [] },
    getMyPayroll: { lines: [] },
    listPayrollExceptions: { exceptions: [] },
    listHistoricalPriceManualReviews: { reviews: [] },
    approvePayrollException: {},
    regeneratePayrollBatch: {},
    submitPayrollBatch: {},
  }
  for (const [name, response] of Object.entries(responses)) {
    mocks.wages[name] = vi.fn().mockResolvedValue(response)
  }
})
afterEach(() => {
  wrappers.splice(0).reverse().forEach(wrapper => wrapper.unmount())
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('payroll workspace restored state and display contracts', () => {
  it('loads restored process once and leaves historical month selection usable with empty results', async () => {
    localStorage.setItem('wageActiveTab', 'process')
    mocks.wages.getProcessSummary.mockImplementation(async month => month === '2026-08'
      ? { summary: [{ process_id: 7, process_name: '历史精车', worker_count: 1, total_quantity: 4, total_wage: 40 }], grand_total_wage: 40 }
      : { summary: [], grand_total_wage: 0 })
    const wrapper = render(WageList)
    await flushPromises()
    expect(mocks.wages.getProcessSummary).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('暂无工序分析数据')
    expect(wrapper.text()).not.toContain('加载中...')
    const month = wrapper.find('input[aria-label="工序分析月份"]')
    expect(month.exists()).toBe(true)
    await month.setValue('2026-08')
    await flushPromises()
    expect(mocks.wages.getProcessSummary).toHaveBeenLastCalledWith('2026-08')
    expect(wrapper.text()).toContain('历史精车')
    expect(wrapper.text()).toContain('¥40.00')
    expect(month.element.value).toBe('2026-08')
  })

  it('shows an identical ten-yuan precise unit price in coverage and the price editor', async () => {
    mocks.permissions = ['wages:prepare']
    localStorage.setItem('wageActiveTab', 'process')
    mocks.wages.getRoutePriceVersionReference.mockResolvedValue({
      items: [{ route_version_id: 81, process_version_id: 71, route_name: '精车路线', process_name: '精车' }],
    })
    const price = { id: 1, route_version_id: 81, process_version_id: 71, status: 'approved', normal_unit_price_micros: 100000 }
    mocks.wages.listRoutePriceVersions.mockResolvedValue({ versions: [price] })
    const workspace = render(WageList)
    await flushPromises()
    expect(workspace.find('.coverage-table').text()).toContain('¥10.0000')
    const editor = render(PriceVersionEditor, {
      props: { open: true, reference: { reference_key: '81:71' }, currentPrice: price },
    })
    expect(editor.find('.current-price-strip').text()).toContain('¥10.0000')
    expect(editor.find('[data-testid="price-unit-input"]').element.value).toBe('10.0000')
  })

  it.each(['wages:view_all', 'wages:export'])(
    'restores process summaries without querying price coverage for %s',
    async permission => {
      mocks.permissions = [permission]
      localStorage.setItem('wageActiveTab', 'process')
      mocks.wages.getProcessSummary.mockResolvedValue({
        summary: [{ process_id: 7, process_name: '只读精车汇总', worker_count: 1, total_quantity: 4, total_wage: 40 }],
        grand_total_wage: 40,
      })
      const wrapper = render(WageList)
      await flushPromises()
      expect(wrapper.vm.activeTab).toBe('process')
      expect(mocks.wages.getProcessSummary).toHaveBeenCalledTimes(1)
      expect(wrapper.find('.distribution-list').text()).toContain('只读精车汇总')
      expect(wrapper.find('.distribution-list').text()).toContain('¥40.00')
      expect(wrapper.find('.coverage-workbench').exists()).toBe(false)
      expect(mocks.wages.getRoutePriceVersionReference).not.toHaveBeenCalled()
      expect(mocks.wages.listRoutePriceVersions).not.toHaveBeenCalled()
      expect(mocks.toast).not.toHaveBeenCalled()
    },
  )

  it.each([
    { permission: 'wages:view_self', expectedTab: '我的工资' },
    { permission: 'wages:view', expectedTab: '实时预估' },
  ])('keeps global analytics hidden for $permission despite persisted process tab', async ({ permission, expectedTab }) => {
    mocks.permissions = [permission]
    localStorage.setItem('wageActiveTab', 'process')
    const wrapper = render(WageList)
    await flushPromises()
    const labels = wrapper.find('.wage-tab-nav').text()
    expect(labels).toContain(expectedTab)
    for (const label of ['月度汇总', '工序分析', '工资对比', '历史趋势', '岗位汇总', '工资预测']) {
      expect(labels).not.toContain(label)
    }
    wrapper.vm.switchTab('process')
    await flushPromises()
    expect(wrapper.vm.activeTab).toBe(permission === 'wages:view_self' ? 'my' : 'piece')
    expect(mocks.wages.getProcessSummary).not.toHaveBeenCalled()
    expect(mocks.wages.getMonthlySummary).not.toHaveBeenCalled()
    expect(mocks.wages.getRoutePriceVersionReference).not.toHaveBeenCalled()
  })

  it('uses real implied prepare permissions when restoring monthly analytics', async () => {
    mocks.permissions = ['wages:prepare']
    localStorage.setItem('wageActiveTab', 'monthly')
    mocks.wages.getMonthlySummary.mockResolvedValue({
      summary: [{ user_id: 4, employee_name: '月度员工', total_quantity: 2, total_wage: 20 }],
      total: 1, grand_total_quantity: 2, grand_total_wage: 20,
    })
    const wrapper = render(WageList)
    await flushPromises()
    expect(wrapper.find('.wage-tab-nav').text()).toContain('工序分析')
    expect(mocks.wages.getMonthlySummary).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('月度员工')
    expect(wrapper.text()).toContain('¥20.00')
    expect(wrapper.text()).not.toContain('加载中...')
  })

  it('loads process after switching tabs and reports errors without trapping the month selector', async () => {
    const wrapper = render(WageList)
    await flushPromises()
    mocks.wages.getProcessSummary.mockRejectedValue(new Error('分析暂不可用'))
    await button(wrapper, '工序分析').trigger('click')
    await flushPromises()
    expect(mocks.wages.getProcessSummary).toHaveBeenCalledTimes(1)
    expect(wrapper.find('input[aria-label="工序分析月份"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无工序分析数据')
    expect(mocks.toast).toHaveBeenCalledWith('加载工序分析失败', 'error')
  })

  it.each([
    { date: new Date(2026, 9, 31, 12), previous: '2026-09', current: '2026-10' },
    { date: new Date(2026, 0, 1, 0, 15), previous: '2025-12', current: '2026-01' },
  ])('defaults comparison to local $previous / $current', async ({ date, previous, current }) => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(date)
    localStorage.setItem('wageActiveTab', 'compare')
    const wrapper = render(WageList)
    const months = wrapper.findAll('input[type="month"]')
    expect(months.map(input => input.element.value)).toEqual([previous, current])
    await button(wrapper, '对比').trigger('click')
    await flushPromises()
    expect(mocks.wages.getMonthlySummary).toHaveBeenNthCalledWith(1, { year_month: previous, page: 1, limit: 2000 })
    expect(mocks.wages.getMonthlySummary).toHaveBeenNthCalledWith(2, { year_month: current, page: 1, limit: 2000 })
  })
})

describe('payroll piecework filters and pagination', () => {
  function piecework() {
    localStorage.setItem('wageActiveTab', 'piece')
    mocks.wages.listWages.mockImplementation(async params => ({
      wages: [{ employee_id: params.page, employee_name: `第${params.page}页员工`, total_quantity: 2, total_wage: 20, details: [] }],
      total: 120,
    }))
    return render(WageList)
  }

  it.each(['includeRework', 'hideZero', 'dateFrom', 'dateTo', 'query'])(
    'returns to page one after changing %s and renders the refreshed employee',
    async filter => {
      const wrapper = piecework()
      await flushPromises()
      await button(wrapper, '下一页 ▶').trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('第2页员工')
      const filters = {
        includeRework: () => wrapper.findAll('input[type="checkbox"]')[0].setValue(true),
        hideZero: () => wrapper.findAll('input[type="checkbox"]')[1].setValue(true),
        dateFrom: () => wrapper.find('input[aria-label="预估开始日期"]').setValue('2026-09-01'),
        dateTo: () => wrapper.find('input[aria-label="预估结束日期"]').setValue('2026-09-30'),
        query: () => button(wrapper, '查询').trigger('click'),
      }
      await filters[filter]()
      await flushPromises()
      const expected = { page: 1, limit: 50 }
      if (filter === 'includeRework') expected.include_rework = '1'
      if (filter === 'hideZero') expected.hide_zero = '1'
      if (filter === 'dateFrom') expected.date_from = '2026-09-01'
      if (filter === 'dateTo') expected.date_to = '2026-09-30'
      expect(mocks.wages.listWages).toHaveBeenLastCalledWith(expected)
      expect(wrapper.text()).toContain('第1页员工')
      expect(wrapper.text()).toContain('第 1 / 3 页')
      expect(wrapper.text()).not.toContain('第2页员工')
    },
  )

  it('normalizes invalid page values and retains the current integer page during refresh', async () => {
    const wrapper = piecework()
    await flushPromises()
    for (const invalid of [new Event('change'), 1.5, 0, -2, '2']) {
      await wrapper.vm.load(invalid)
      await flushPromises()
      expect(mocks.wages.listWages).toHaveBeenLastCalledWith({ page: 1, limit: 50 })
      expect(wrapper.text()).toContain('第 1 / 3 页')
    }
    await wrapper.vm.load(2)
    await wrapper.vm.load()
    await flushPromises()
    expect(mocks.wages.listWages).toHaveBeenLastCalledWith({ page: 2, limit: 50 })
    expect(wrapper.text()).toContain('第2页员工')
  })
})

describe('payroll input drift and exception approval workflow', () => {
  it('warns in list and detail, blocks stale submissions and submits only the refreshed version', async () => {
    mocks.permissions = ['wages:prepare']
    let current = batch({ input_changed: true })
    mocks.wages.listPayrollBatches.mockImplementation(async () => ({ batches: [{ ...current }] }))
    mocks.wages.getPayrollBatch = vi.fn().mockImplementation(async () => ({ batch: { ...current }, lines: [], exceptions: [] }))
    mocks.wages.regeneratePayrollBatch.mockImplementation(async () => {
      current = batch({ row_version: 4 })
      return { batch: { ...current } }
    })
    const wrapper = render(PayrollLedgerTab)
    await flushPromises()
    expect(wrapper.find('tbody').text()).toContain('输入已变化，请重算后提交')
    expect(button(wrapper, '提交')).toBeUndefined()
    await button(wrapper, '查看').trigger('click')
    await flushPromises()
    expect(wrapper.find('.payroll-detail-header').text()).toContain('输入已变化，请重算后提交')
    await state(wrapper).submit(current)
    expect(mocks.wages.submitPayrollBatch).not.toHaveBeenCalled()
    expect(mocks.toast).toHaveBeenCalledWith('输入已变化，请重算后提交', 'error')
    await button(wrapper, '重算').trigger('click')
    await flushPromises()
    expect(mocks.wages.regeneratePayrollBatch).toHaveBeenCalledWith(8, 3)
    expect(wrapper.text()).not.toContain('输入已变化，请重算后提交')
    await button(wrapper, '提交').trigger('click')
    await flushPromises()
    expect(mocks.wages.submitPayrollBatch).toHaveBeenCalledWith(8, 4)
  })

  it('reloads the invalidated batch on return from approved exceptions before regeneration', async () => {
    mocks.permissions = ['wages:prepare', 'wages:approve']
    let current = batch({ status: 'exceptions_pending', exception_count: 1 })
    let exception = {
      id: 9, status: 'proposed', payroll_month: '2026-09', version: 1,
      exception_type: 'missing_price', proposed_price_micros: 100000,
      snapshot_json: '{"employee_name":"核定员工","order_no":"ORD-9"}',
    }
    mocks.wages.listPayrollBatches.mockImplementation(async () => ({ batches: [{ ...current }] }))
    mocks.wages.listPayrollExceptions.mockImplementation(async () => ({ exceptions: [{ ...exception }] }))
    mocks.wages.approvePayrollException.mockImplementation(async () => {
      current = batch({ status: 'exceptions_pending', row_version: 4, input_changed: true })
      exception = { ...exception, status: 'approved' }
      return { batch_row_version: 4 }
    })
    mocks.wages.regeneratePayrollBatch.mockImplementation(async () => {
      current = batch({ row_version: 5 })
      return { batch: { ...current } }
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = render(WageList)
    await flushPromises()
    await button(wrapper, '异常处理').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('¥10.0000')
    await button(wrapper, '批准').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已批准')
    expect(mocks.toast).toHaveBeenCalledWith('异常方案已批准，请返回台账重算')
    await button(wrapper, '批次台账').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('输入已变化，请重算后提交')
    expect(button(wrapper, '提交')).toBeUndefined()
    await button(wrapper, '重算').trigger('click')
    await flushPromises()
    expect(mocks.wages.regeneratePayrollBatch).toHaveBeenCalledWith(8, 4)
    await button(wrapper, '提交').trigger('click')
    await flushPromises()
    expect(mocks.wages.submitPayrollBatch).toHaveBeenCalledWith(8, 5)
  })
})
