import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PayrollLedgerTab from '@/views/wage/PayrollLedgerTab.vue'

const mocks = vi.hoisted(() => ({ wages: {}, toast: vi.fn() }))

vi.mock('@/lib/api.js', () => ({ api: { domains: { wages: mocks.wages } } }))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))

describe('payroll period control', () => {
  beforeEach(() => {
    mocks.toast.mockReset()
    mocks.wages.listPayrollBatches = vi.fn().mockResolvedValue({ batches: [] })
    mocks.wages.getPayrollPeriodControl = vi.fn().mockResolvedValue({
      payroll_month: '2026-09',
      status: 'locked',
      version: 2,
      source_cutoff_at: '2026-10-01 07:00:00',
      pending_exception_count: 0,
      can_regenerate: false,
      can_adjust: false,
      requires_revision: true,
    })
  })

  it.each([
    { status: 'unstarted', label: '未生成', can_adjust: true, can_regenerate: false, requires_revision: false },
    { status: 'draft', label: '草稿', can_adjust: true, can_regenerate: true, requires_revision: false },
    { status: 'locked', label: '已锁定', can_adjust: false, can_regenerate: false, requires_revision: true },
  ])('renders $label period controls', async control => {
    mocks.wages.getPayrollPeriodControl.mockResolvedValue({
      payroll_month: '2026-09',
      status: control.status,
      version: control.status === 'unstarted' ? null : 2,
      source_cutoff_at: control.status === 'unstarted' ? null : '2026-10-01 07:00:00',
      exception_count: 1,
      pending_exception_count: 1,
      can_regenerate: control.can_regenerate,
      can_adjust: control.can_adjust,
      requires_revision: control.requires_revision,
    })
    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()

    expect(mocks.wages.getPayrollPeriodControl).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-\d{2}$/))
    expect(wrapper.get('[data-testid="payroll-period-control"]').text()).toContain(control.label)
    if (control.status !== 'unstarted') expect(wrapper.text()).toContain('V2')
    expect(wrapper.text()).toContain(control.can_adjust ? '补差/调整允许' : '补差/调整须通过修订批次')
    expect(wrapper.text()).toContain(control.can_adjust ? '数据截止' : '不允许直接新增调整')
    wrapper.unmount()
  })
})
