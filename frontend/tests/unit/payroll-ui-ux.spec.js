import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  permissions: ['wages:view_all', 'wages:prepare', 'wages:approve'],
  wages: {},
  toast: vi.fn(),
  navigate: vi.fn(),
  switchTab: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({ api: { domains: { wages: mocks.wages } } }))
vi.mock('@/lib/auth.js', () => ({
  auth: { user: { id: 7 } },
  can: permission => mocks.permissions.includes(permission),
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))
vi.mock('@/lib/router.js', () => ({ navigate: mocks.navigate, router: { params: {} } }))
vi.mock('@/composables/useWage.js', () => ({ useWage: () => ({ switchTab: mocks.switchTab }) }))
vi.mock('@/composables/wage/useWageWorkspace.js', () => ({
  useWageWorkspace: () => ({
    activeTab: { value: 'ledger' },
    tabGroups: {
      value: [
        { id: '核算', label: '核算', tabs: [{ id: 'ledger', label: '批次台账' }, { id: 'exceptions', label: '异常处理' }] },
        { id: '结算', label: '结算', tabs: [{ id: 'settlement', label: '导出对账' }] },
        { id: '查询', label: '查询', tabs: [{ id: 'my', label: '我的工资' }] },
        { id: '分析', label: '分析', tabs: [{ id: 'monthly', label: '月度汇总' }] },
      ],
    },
    switchTab: mocks.switchTab,
    priceIntent: {},
  }),
}))

import PayrollExceptionsTab from '@/views/wage/PayrollExceptionsTab.vue'
import PayrollLedgerTab from '@/views/wage/PayrollLedgerTab.vue'
import WageList from '@/views/WageList.vue'

describe('payroll UI/UX workflow controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    mocks.permissions = ['wages:view_all', 'wages:prepare', 'wages:approve']
    mocks.wages.listPayrollBatches = vi.fn().mockResolvedValue({ batches: [] })
    mocks.wages.getPayrollPeriodControl = vi.fn().mockResolvedValue(null)
    mocks.wages.listPayrollAuditFindings = vi.fn().mockResolvedValue({ audit_findings: [] })
    mocks.wages.listPayrollExceptions = vi.fn().mockResolvedValue({
      exceptions: [
        { id: 11, status: 'proposed', exception_type: 'missing_price', payroll_month: '2026-11', version: 1, snapshot_json: '{}' },
        { id: 12, status: 'proposed', exception_type: 'missing_rework_rate', payroll_month: '2026-11', version: 1, snapshot_json: '{}' },
      ],
    })
    mocks.wages.approvePayrollException = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('continues bulk approval after one item fails and shows the summary', async () => {
    mocks.wages.approvePayrollException
      .mockResolvedValueOnce({ ok: true })
      .mockRejectedValueOnce(new Error('版本已被其他人处理'))
    const wrapper = mount(PayrollExceptionsTab)
    await flushPromises()

    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    expect(checkboxes[1].element.checked).toBe(true)
    expect(checkboxes[2].element.checked).toBe(true)
    const bulkButton = wrapper.findAll('button').find(button => button.text().includes('集中批准'))
    expect(bulkButton).toBeTruthy()
    expect(bulkButton.text()).toContain('2')
    await bulkButton.trigger('click')
    await flushPromises()

    expect(mocks.wages.approvePayrollException).toHaveBeenNthCalledWith(1, 11)
    expect(mocks.wages.approvePayrollException).toHaveBeenNthCalledWith(2, 12)
    expect(wrapper.text()).toContain('成功 1 条，失败 1 条')
    expect(wrapper.text()).toContain('版本已被其他人处理')
    wrapper.unmount()
  })

  it('keeps the batch primary action permission-aware and status-driven', async () => {
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [{ id: 1, payroll_month: '2026-11', version: 1, status: 'draft', input_changed: true, legacy_imported: false }],
    })
    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()
    expect(wrapper.text()).toContain('重算')
    expect(wrapper.text()).toContain('查看')
    expect(wrapper.get('[data-testid="batch-primary-action-1"]').text()).toBe('重算')
    wrapper.unmount()

    mocks.permissions = ['wages:view_all']
    const readOnly = mount(PayrollLedgerTab)
    await flushPromises()
    expect(readOnly.text()).toContain('查看')
    expect(readOnly.findAll('button').some(button => button.text() === '重算')).toBe(false)
    readOnly.unmount()
  })

  it('switches to the exceptions tab from the primary action', async () => {
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [{ id: 2, payroll_month: '2026-11', version: 1, status: 'exceptions_pending' }],
    })
    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()

    await wrapper.find('.payroll-row-actions button.btn-primary').trigger('click')

    expect(mocks.switchTab).toHaveBeenCalledWith('exceptions')
    expect(mocks.navigate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('switches to the settlement tab from the primary action', async () => {
    mocks.permissions = ['wages:view_all', 'wages:export']
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [{ id: 3, payroll_month: '2026-11', version: 1, status: 'confirmed' }],
    })
    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()

    await wrapper.find('.payroll-row-actions button.btn-primary').trigger('click')

    expect(mocks.switchTab).toHaveBeenCalledWith('settlement')
    expect(mocks.navigate).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['核算', 'ledger'],
    ['结算', 'settlement'],
    ['查询', 'my'],
    ['分析', 'monthly'],
  ])('activates the %s group entry tab', async (label, tabId) => {
    const wrapper = shallowMount(WageList)
    const headings = wrapper.findAll('button.wage-tab-group-heading')
    const heading = headings.find(button => button.text() === label)

    expect(heading).toBeTruthy()
    expect(headings[0].attributes('aria-pressed')).toBe('true')
    await heading.trigger('click')

    expect(mocks.switchTab).toHaveBeenCalledWith(tabId)
    wrapper.unmount()
  })
})
