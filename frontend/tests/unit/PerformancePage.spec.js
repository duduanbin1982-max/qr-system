import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PerformancePage from '@/views/PerformancePage.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  performanceRules: vi.fn(),
  performanceOverview: vi.fn(),
  performanceScores: vi.fn(),
  performancePlans: vi.fn(),
  listPerformanceBatches: vi.fn(),
  performanceBatchDetail: vi.fn(),
  submitPerformanceSupervisorReview: vi.fn(),
  submitPerformanceApproval: vi.fn(),
  approvePerformanceBatch: vi.fn(),
  returnPerformanceBatch: vi.fn(),
  cancelPerformanceBatch: vi.fn(),
  createPerformanceBatch: vi.fn(),
  createPerformanceRevision: vi.fn(),
  performanceBatchComparison: vi.fn(),
  performanceBatchExceptions: vi.fn(),
  listPerformanceRuleVersions: vi.fn(),
  listPerformanceTargets: vi.fn(),
  approvePerformanceTarget: vi.fn(),
  createPerformanceTarget: vi.fn(),
  transitionPerformancePlan: vi.fn(),
  addPerformancePlanEvidence: vi.fn(),
  reassessPerformancePlan: vi.fn(),
  getPerformancePlan: vi.fn(),
  getPerformanceDepartmentScopes: vi.fn(),
  replacePerformanceDepartmentScopes: vi.fn(),
  listUsers: vi.fn(),
  listPositions: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      performance: {
        performanceRules: mocks.performanceRules,
        performanceOverview: mocks.performanceOverview,
        performanceScores: mocks.performanceScores,
        performancePlans: mocks.performancePlans,
        listPerformanceBatches: mocks.listPerformanceBatches,
        performanceBatchDetail: mocks.performanceBatchDetail,
        submitPerformanceSupervisorReview: mocks.submitPerformanceSupervisorReview,
        submitPerformanceApproval: mocks.submitPerformanceApproval,
        approvePerformanceBatch: mocks.approvePerformanceBatch,
        returnPerformanceBatch: mocks.returnPerformanceBatch,
        cancelPerformanceBatch: mocks.cancelPerformanceBatch,
        createPerformanceBatch: mocks.createPerformanceBatch,
        createPerformanceRevision: mocks.createPerformanceRevision,
        performanceBatchComparison: mocks.performanceBatchComparison,
        performanceBatchExceptions: mocks.performanceBatchExceptions,
        listPerformanceRuleVersions: mocks.listPerformanceRuleVersions,
        listPerformanceTargets: mocks.listPerformanceTargets,
        approvePerformanceTarget: mocks.approvePerformanceTarget,
        createPerformanceTarget: mocks.createPerformanceTarget,
        transitionPerformancePlan: mocks.transitionPerformancePlan,
        addPerformancePlanEvidence: mocks.addPerformancePlanEvidence,
        reassessPerformancePlan: mocks.reassessPerformancePlan,
        getPerformancePlan: mocks.getPerformancePlan,
        getPerformanceDepartmentScopes: mocks.getPerformanceDepartmentScopes,
        replacePerformanceDepartmentScopes: mocks.replacePerformanceDepartmentScopes,
      },
      users: { listUsers: mocks.listUsers },
      positions: { listPositions: mocks.listPositions },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  auth: { user: { id: 99, name: '测试用户' } },
  can: vi.fn(permission => mocks.permissions.has(permission)),
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


const scorePayload = () => ({
  items: [
    {
      id: 101,
      user_id: 1,
      user_name: '正式员工',
      employee_no: 'P001',
      department_name: '生产部',
      position_name: '焊工',
      eligibility_status: 'eligible',
      eligible: true,
      output_qty: 120,
      report_count: 5,
      output_score: 32,
      quality_score: 28,
      delivery_score: 14,
      discipline_score: 10,
      improvement_score: 8,
      total_score: 92,
      rank_no: 1,
      rank_total: 2,
      warning_level: 'green',
    },
    {
      id: 102,
      user_id: 2,
      user_name: '数据不足员工',
      employee_no: 'P002',
      department_name: '生产部',
      position_name: '焊工',
      eligibility_status: 'insufficient_data',
      eligibility_reason: '当月有效工作日不足',
      eligible: false,
      output_qty: 8,
      total_score: null,
      rank_no: null,
      rank_total: null,
      warning_level: null,
    },
  ],
  total: 2,
  summary: {
    total: 2,
    eligible_count: 1,
    insufficient_data_count: 1,
    avg_score: 92,
    green: 1,
    yellow: 0,
    orange: 0,
    red: 0,
  },
  position_options: [{ id: 7, name: '焊工', employee_count: 2 }],
  result_source: 'ledger_v2',
  batch_id: 10,
  version: 3,
  batch_status: 'approved',
  period_start: '2026-07-01 07:00:00',
  period_end: '2026-08-01 07:00:00',
  year_month: '2026-07',
})

const batch = (overrides = {}) => ({
  id: 10,
  production_month: '2026-07',
  version: 3,
  status: 'draft',
  row_version: 4,
  prepared_by: 99,
  prepared_by_name: '测试用户',
  score_count: 2,
  pending_exception_count: 0,
  allowed_actions: ['submit_supervisor_review', 'cancel'],
  ...overrides,
})


describe('PerformancePage versioned ledger', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.permissions = new Set(['performance:view_all'])
    mocks.performanceRules.mockResolvedValue({ weights: { output: 35, quality: 30, delivery: 15, discipline: 10, improvement: 10 } })
    mocks.performanceOverview.mockResolvedValue({ display_month: '2026-07', months: [{ year_month: '2026-07' }] })
    mocks.performanceScores.mockResolvedValue(scorePayload())
    mocks.performancePlans.mockResolvedValue({ plans: [] })
    mocks.listPerformanceBatches.mockResolvedValue({ items: [batch()], total: 1 })
    mocks.performanceBatchDetail.mockResolvedValue({
      ...batch(),
      batch: batch(),
      scores: scorePayload().items,
      scores_total: 2,
      events: [],
      allowed_actions: ['submit_supervisor_review', 'cancel'],
    })
    mocks.performanceBatchComparison.mockResolvedValue({ items: [] })
    mocks.performanceBatchExceptions.mockResolvedValue({ items: [], total: 0 })
    mocks.listPerformanceRuleVersions.mockResolvedValue([])
    mocks.listPerformanceTargets.mockResolvedValue([])
    mocks.listUsers.mockResolvedValue({ users: [] })
    mocks.listPositions.mockResolvedValue([])
  })

  it('shows immutable result metadata and removes Legacy generation language', async () => {
    const wrapper = mount(PerformancePage)
    await flushPromises()

    expect(wrapper.get('[data-testid="result-source"]').text()).toContain('V2 台账')
    expect(wrapper.get('[data-testid="result-version"]').text()).toContain('V3')
    expect(wrapper.get('[data-testid="result-status"]').text()).toContain('已批准')
    expect(wrapper.get('[data-testid="production-period"]').text()).toContain('2026-07-01 07:00:00')
    expect(wrapper.get('[data-testid="production-period"]').text()).toContain('2026-08-01 07:00:00')
    expect(wrapper.text()).not.toContain('按同岗位当月最高产量')
    expect(wrapper.text()).not.toContain('生成/重算本月评分')
    expect(wrapper.text()).not.toContain('岗位最高产量')
  })

  it('renders insufficient data without score, grade, or rank', async () => {
    const wrapper = mount(PerformancePage)
    await flushPromises()

    const row = wrapper.get('[data-testid="score-row-2"]')
    expect(row.text()).toContain('数据不足')
    expect(row.text()).toContain('当月有效工作日不足')
    expect(row.find('[data-testid="score-grade"]').exists()).toBe(false)
    expect(row.find('[data-testid="score-rank"]').exists()).toBe(false)
    expect(row.find('[data-testid="score-total"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="eligible-count"]').text()).toContain('1')
    expect(wrapper.get('[data-testid="insufficient-count"]').text()).toContain('1')
  })

  it('shows workflow views by operation permission and limits department scope to administrators', async () => {
    mocks.permissions = new Set(['performance:view_self'])
    const employee = mount(PerformancePage)
    await flushPromises()
    expect(employee.find('[data-testid="tab-batches"]').exists()).toBe(false)
    expect(employee.get('[data-testid="tab-plans"]').exists()).toBe(true)
    employee.unmount()

    mocks.permissions = new Set(['performance:view_department', 'performance:review_department'])
    const reviewer = mount(PerformancePage)
    await flushPromises()
    expect(reviewer.get('[data-testid="tab-batches"]').exists()).toBe(true)
    expect(reviewer.find('[data-testid="tab-targets"]').exists()).toBe(false)
    expect(reviewer.find('[data-testid="tab-scopes"]').exists()).toBe(false)
    reviewer.unmount()

    mocks.permissions = new Set(['performance:prepare', 'users:admin'])
    const admin = mount(PerformancePage)
    await flushPromises()
    expect(admin.get('[data-testid="tab-targets"]').exists()).toBe(true)
    expect(admin.get('[data-testid="tab-scopes"]').exists()).toBe(true)
  })

  it('sends row version and an idempotency key, then refreshes after a conflict', async () => {
    mocks.permissions = new Set(['performance:prepare'])
    const conflict = Object.assign(new Error('版本冲突'), { status: 409 })
    mocks.submitPerformanceSupervisorReview.mockRejectedValue(conflict)
    const wrapper = mount(PerformancePage)
    await flushPromises()

    await wrapper.get('[data-testid="tab-batches"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="batch-action-submit-review"]').trigger('click')
    await flushPromises()

    expect(mocks.submitPerformanceSupervisorReview).toHaveBeenCalledWith(10, expect.objectContaining({
      row_version: 4,
      idempotency_key: expect.stringMatching(/^performance-ui:submit-supervisor-review:/),
    }))
    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('冲突'), 'error')
    expect(wrapper.get('[data-testid="batch-action-submit-review"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('草稿')
  })

  it('never offers a direct close action for improvement plans', async () => {
    mocks.permissions = new Set(['performance:view_all', 'performance:plan_manage', 'performance:plan_reassess'])
    mocks.performancePlans.mockResolvedValue({ plans: [{
      id: 31,
      user_id: 1,
      employee_name_snapshot: '正式员工',
      production_month: '2026-07',
      warning_level_snapshot: 'orange',
      goal: '一次合格率达到 98%',
      actions: '现场培训并跟踪',
      owner_name_snapshot: '生产主管',
      due_date: '2026-08-20',
      status: 'active',
      row_version: 2,
    }] })
    const wrapper = mount(PerformancePage)
    await flushPromises()
    await wrapper.get('[data-testid="tab-plans"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('关闭复评')
    expect(wrapper.text()).not.toContain('已完成复评')
    expect(wrapper.get('[data-testid="plan-evidence-31"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="plan-direct-close-31"]').exists()).toBe(false)
  })
})
