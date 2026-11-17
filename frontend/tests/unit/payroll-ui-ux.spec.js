import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  permissions: ['wages:view_all', 'wages:prepare', 'wages:approve'],
  wages: {},
  toast: vi.fn(),
  navigate: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({ api: { domains: { wages: mocks.wages } } }))
vi.mock('@/lib/auth.js', () => ({
  auth: { user: { id: 7 } },
  can: permission => mocks.permissions.includes(permission),
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))
vi.mock('@/lib/router.js', () => ({ navigate: mocks.navigate, router: { params: {} } }))

import PayrollExceptionsTab from '@/views/wage/PayrollExceptionsTab.vue'
import PayrollLedgerTab from '@/views/wage/PayrollLedgerTab.vue'

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
    await checkboxes[1].setValue(true)
    await checkboxes[2].setValue(true)
    const bulkButton = wrapper.findAll('button').find(button => button.text() === '集中批准')
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
    expect(wrapper.text()).toContain('更多')
    wrapper.unmount()

    mocks.permissions = ['wages:view_all']
    const readOnly = mount(PayrollLedgerTab)
    await flushPromises()
    expect(readOnly.text()).toContain('查看')
    expect(readOnly.findAll('button').some(button => button.text() === '重算')).toBe(false)
    readOnly.unmount()
  })
})
