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

  it('loads paginated source drilldown for an employee line', async () => {
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [{ id: 7, payroll_month: '2026-09', version: 2, status: 'confirmed', payable_wage_cents: 1000 }],
    })
    mocks.wages.getPayrollBatch = vi.fn().mockResolvedValue({
      batch: { id: 7, payroll_month: '2026-09', version: 2, status: 'confirmed', period_start: '2026-09-01', period_end: '2026-10-01', source_cutoff_at: '2026-10-01 07:00:00' },
      lines: [{ id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11', normal_quantity: 1, rework_quantity: 0, normal_wage_cents: 1000, rework_wage_cents: 0, bonus_cents: 0, allowance_cents: 0, deduction_cents: 0, payable_wage_cents: 1000 }],
      details: [], exceptions: [], audit_findings: [],
    })
    mocks.wages.getPayrollLineSources = vi.fn().mockResolvedValue({
      calculation_version: 3,
      line: { id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11' },
      items: [{ id: 101, source_type_label: '正常报工', order_no_snapshot: 'SO-1', product_code_snapshot: 'P-1', route_name_snapshot: '路线A', process_name_snapshot: '工序A', quantity: 1, unit_price_yuan: '1.0000', amount_cents: 100 }],
      total: 1, page: 1, limit: 50,
    })
    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看来源').trigger('click')
    await flushPromises()

    expect(mocks.wages.getPayrollBatch).toHaveBeenCalledWith(7)
    expect(mocks.wages.getPayrollLineSources).toHaveBeenCalledWith(7, 11, { page: 1, limit: 50 })
    expect(wrapper.text()).toContain('来源下钻')
    expect(wrapper.text()).toContain('正常报工')
    expect(wrapper.text()).toContain('SO-1')
    wrapper.unmount()
  })

  it('pins source pagination to the calculation version and refreshes after a recalculation conflict', async () => {
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [{ id: 7, payroll_month: '2026-09', version: 2, status: 'confirmed', payable_wage_cents: 1000 }],
    })
    mocks.wages.getPayrollBatch = vi.fn().mockResolvedValue({
      batch: { id: 7, payroll_month: '2026-09', version: 2, status: 'confirmed' },
      lines: [{ id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11' }],
      details: [], exceptions: [], audit_findings: [],
    })
    const conflict = Object.assign(new Error('工资批次已重算，来源快照已更新，请重新打开批次'), { status: 409 })
    mocks.wages.getPayrollLineSources = vi.fn()
      .mockResolvedValueOnce({
        calculation_version: 4,
        line: { id: 11, employee_name_snapshot: '员工A' },
        items: [{ id: 101, source_type_label: '正常报工' }],
        total: 51, page: 1, limit: 50,
      })
      .mockRejectedValueOnce(conflict)

    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看来源').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '下一页').trigger('click')
    await flushPromises()

    expect(mocks.wages.getPayrollLineSources).toHaveBeenNthCalledWith(
      1, 7, 11, { page: 1, limit: 50 },
    )
    expect(mocks.wages.getPayrollLineSources).toHaveBeenNthCalledWith(
      2, 7, 11, { page: 2, limit: 50, calculation_version: 4 },
    )
    expect(mocks.wages.getPayrollBatch).toHaveBeenCalledTimes(2)
    expect(mocks.toast).toHaveBeenCalledWith(conflict.message, 'error')
    wrapper.unmount()
  })

  it('keeps the pinned source version when navigating back to the first page', async () => {
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [{ id: 7, payroll_month: '2026-09', version: 2, status: 'confirmed', payable_wage_cents: 1000 }],
    })
    mocks.wages.getPayrollBatch = vi.fn().mockResolvedValue({
      batch: { id: 7, payroll_month: '2026-09', version: 2, status: 'confirmed' },
      lines: [{ id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11' }],
      details: [], exceptions: [], audit_findings: [],
    })
    mocks.wages.getPayrollLineSources = vi.fn()
      .mockResolvedValueOnce({
        calculation_version: 6,
        line: { id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11' },
        items: [{ id: 101, source_type_label: '正常报工' }], total: 51, page: 1, limit: 50,
      })
      .mockResolvedValueOnce({
        calculation_version: 6,
        line: { id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11' },
        items: [{ id: 102, source_type_label: '正常报工' }], total: 51, page: 2, limit: 50,
      })
      .mockResolvedValueOnce({
        calculation_version: 6,
        line: { id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11' },
        items: [{ id: 101, source_type_label: '正常报工' }], total: 51, page: 1, limit: 50,
      })

    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看来源').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '下一页').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '上一页').trigger('click')
    await flushPromises()

    expect(mocks.wages.getPayrollLineSources).toHaveBeenNthCalledWith(
      3, 7, 11, { page: 1, limit: 50, calculation_version: 6 },
    )
    wrapper.unmount()
  })

  it('ignores a stale source response after switching batches', async () => {
    let resolveSources
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [
        { id: 7, payroll_month: '2026-09', version: 2, status: 'confirmed', payable_wage_cents: 1000 },
        { id: 8, payroll_month: '2026-10', version: 1, status: 'confirmed', payable_wage_cents: 1200 },
      ],
    })
    mocks.wages.getPayrollBatch = vi.fn()
      .mockResolvedValueOnce({
        batch: { id: 7, payroll_month: '2026-09', version: 2 },
        lines: [{ id: 11, employee_name_snapshot: '员工A', employee_no_snapshot: 'A-11' }],
        details: [], exceptions: [], audit_findings: [],
      })
      .mockResolvedValueOnce({
        batch: { id: 8, payroll_month: '2026-10', version: 1 },
        lines: [{ id: 22, employee_name_snapshot: '员工B', employee_no_snapshot: 'B-22' }],
        details: [], exceptions: [], audit_findings: [],
      })
    mocks.wages.getPayrollLineSources = vi.fn().mockImplementation(() => new Promise(resolve => {
      resolveSources = resolve
    }))

    const wrapper = mount(PayrollLedgerTab)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看来源').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '关闭').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看').trigger('click')
    await flushPromises()

    resolveSources({
      line: { id: 11, employee_name_snapshot: '员工A' },
      items: [{ id: 101, source_type_label: '旧批次来源' }],
      total: 1, page: 1, limit: 50,
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('旧批次来源')
    wrapper.unmount()
  })
})
