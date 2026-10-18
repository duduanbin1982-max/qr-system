import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import GanttChart from '@/views/GanttChart.vue'

const mocks = vi.hoisted(() => ({
  updateScheduleOrderPriority: vi.fn(),
  listOrderScheduleRevisions: vi.fn(),
  getScheduleRevision: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { production: {
    updateScheduleOrderPriority: mocks.updateScheduleOrderPriority,
    listOrderScheduleRevisions: mocks.listOrderScheduleRevisions,
    getScheduleRevision: mocks.getScheduleRevision,
  } } },
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

let ganttState
let wrapper

vi.mock('@/composables/useGantt.js', () => ({
  useGantt: () => ganttState,
}))

const fn = () => vi.fn()

function createState() {
  const node = {
    id: 41,
    process_id: 7,
    process_name: '焊接',
    node_code: 'WELD-01',
    node_name: '焊接-01',
    capacity_mode: 'exclusive',
    capacity_minutes: 540,
    status: 'active',
  }
  const productionNodeManager = {
    state: {
      productionNodes: [node],
      productionCalendars: [{ id: 3, calendar_name: '九小时工作日历' }],
      currentNodeId: null,
      nodeSummary: { production_node_id: 41, capability_count: 0, future_override_count: 0 },
      nodeSummaryLoading: false,
      nodeSummaryError: '',
      nodesByProcess: [{ process_id: 7, process_name: '焊接', nodes: [node] }],
      nodesLoading: false,
      nodesError: '',
      nodeForm: {},
      nodeSaving: false,
      overrideForm: {},
      nodeOverrides: [],
      overridesLoading: false,
      overridesError: '',
      overrideSaving: false,
      capabilityForm: { capabilities: [] },
      capabilitiesLoading: false,
      capabilitiesError: '',
      capabilitySaving: false,
    },
    permissions: {
      canViewNodes: true,
      canManageNodes: true,
      canManageCapabilities: true,
      canManageCalendars: true,
    },
    actions: {
      loadNodes: fn(),
      selectNodeContext: fn(),
      loadNodeSummary: fn(),
      rollbackPanel: fn(),
      resetWorkbenchSession: fn(),
      resetNodeForm: fn(),
      editNode: fn(),
      saveNode: fn(),
      prepareOverride: fn(),
      loadOverrides: fn(),
      createCalendarOverride: fn(),
      cancelOverride: fn(),
      loadCapabilities: fn(),
      addCapability: fn(),
      removeCapability: fn(),
      saveCapabilities: fn(),
    },
  }
  return {
    stats: { total: 1, producing: 1, pending: 0, completed: 0 },
    riskSummary: { overdue: 0, high: 0, medium: 0, delayed: 0, totalDelayMinutes: 0 },
    riskFilter: 'all',
    viewMode: ref('operations'),
    scheduleScope: 'active',
    canViewNodes: true,
    canManageNodes: true,
    canManageCapabilities: true,
    canManageCalendars: true,
    canManageDowntime: true,
    canGenerateSchedules: true,
    canAdjustSchedules: true,
    canLockSchedules: true,
    canUnlockSchedules: true,
    canSubmitSchedules: true,
    canApproveSchedules: true,
    canRejectSchedules: true,
    canPublishSchedules: true,
    canEdit: true,
    setViewMode: vi.fn(mode => { ganttState.viewMode.value = mode }),
    setScheduleScope: fn(),
    zoomOut: fn(),
    zoomIn: fn(),
    exportImage: fn(),
    exportScheduleCsv: fn(),
    capacityProcessFilter: '',
    capacityNodeFilter: '',
    capacityOrderFilter: '',
    capacityRiskFilter: 'all',
    processOptions: [{ id: 7, name: '焊接' }],
    capacityNodes: [node],
    capacitySummary: { total: 1, planned: 0, blocked: 1, conflicts: 0, minutes: 0 },
    conflictAudit: { line_conflicts: 0, conflicts: [], risk_counts: {}, risk_orders: [] },
    generationOrderId: '',
    generationStartDate: '2026-09-19',
    capacityOrders: [],
    selectedReplanOrder: null,
    prepareGeneration: fn(),
    generateSchedule: fn(),
    replanOrderId: ref(''),
    replanStartAt: '2026-09-19T08:00',
    replanReason: '',
    replanResult: null,
    prepareDynamicReplan: fn(),
    dynamicReplanSchedule: fn(),
    prepareAutoPlan: fn(),
    loadCapacity: fn(),
    autoPlanVisible: false,
    autoPlanStartDate: '2026-09-19',
    autoPlanLimit: 100,
    autoPlanKey: '',
    autoPlanLoading: false,
    autoPlanResult: null,
    runAutoPlan: fn(),
    downtimeForm: { production_node_id: 41, start_at: '', end_at: '', reason: '' },
    createDowntime: fn(),
    downtimeLoading: false,
    downtimeEvents: [],
    loadDowntime: fn(),
    cancelDowntime: fn(),
    capacityLoading: false,
    operationSchedules: [],
    filteredOperations: [{
      id: 501,
      order_id: 12,
      order_no: '26091901',
      process_id: 7,
      process_name: '焊接',
      production_node_id: 41,
      node_code: 'WELD-01',
      node_name: '焊接-01',
      schedule_status: 'blocked',
      blocked_code: 'NO_COMPATIBLE_NODE',
      locked: true,
      revision_item_id: 901,
      schedule_revision_id: 77,
      revision_status: 'draft',
      revision_approval_status: 'draft',
      allocations: [],
    }],
    nodeLabel: row => `${row.node_code} · ${row.node_name}`,
    allocationLabel: fn(),
    standardScopeLabel: () => '-',
    operationRiskLevel: () => 'none',
    operationRisk: () => ({ risk_reason: '', delay_minutes: 0 }),
    riskColor: () => 'green',
    riskIcon: () => '🟢',
    riskLabel: () => '正常',
    formatRiskMinutes: minutes => `${minutes} 分钟`,
    blockedCode: row => row.blocked_code,
    blockedMessage: () => '没有满足能力要求的生产节点',
    prepareAdjustment: fn(),
    lockOperation: fn(),
    unlockOperation: fn(),
    submitRevision: fn(),
    approveRevision: fn(),
    rejectRevision: fn(),
    publishRevision: fn(),
    revisionState: row => {
      if (row.revision_status === 'published') return 'published'
      if (row.revision_approval_status === 'submitted') return 'pending_approval'
      if (row.revision_approval_status === 'approved') return 'approved'
      if (row.revision_approval_status === 'rejected') return 'rejected'
      return row.revision_status || 'draft'
    },
    revisionStatusLabel: () => '草稿',
    loading: false,
    filteredOrders: [],
    orders: [],
    ganttData: { totalDays: 0, days: [] },
    dayWidth: 30,
    orderKeyword: '',
    productKeyword: '',
    priorityFilter: 'all',
    statusFilter: 'all',
    lockedFilter: 'all',
    deadlineFrom: '',
    deadlineTo: '',
    savedFilters: [],
    saveFilter: fn(),
    applySavedFilter: fn(),
    deleteSavedFilter: fn(),
    resetFilters: fn(),
    batchDays: 1,
    batchShift: fn(),
    shiftDays: fn(),
    selectedOrderIds: [],
    showEditModal: false,
    editForm: { plan_start: '', plan_end: '' },
    undoLastDrag: fn(),
    saveEditDates: fn(),
    orderDrawerOpen: ref(false),
    selectedScheduleOrder: ref(null),
    selectedOrderOperations: [],
    selectedOrderRevisions: [],
    orderDrawerLoading: false,
    orderDrawerError: '',
    openOrderDrawer: fn(),
    closeOrderDrawer: vi.fn(() => { ganttState.orderDrawerOpen.value = false }),
    load: fn(),
    showNodeMgr: true,
    productionNodeManager,
    nodesLoading: false,
    nodesByProcess: [{ process_id: 7, process_name: '焊接', nodes: [node] }],
    productionNodes: [node],
    productionCalendars: [{ id: 3, calendar_name: '九小时工作日历' }],
    nodeForm: {
      id: null,
      process_id: '',
      node_code: '',
      node_name: '',
      capacity_mode: 'exclusive',
      calendar_id: '',
      status: 'active',
      reason: '',
      idempotency_key: '',
    },
    overrideForm: {
      production_node_id: 41,
      start_at: '',
      end_at: '',
      override_type: 'unavailable',
      reason: '',
      idempotency_key: '',
    },
    capabilityForm: { production_node_id: '', node_label: '', capabilities: [], reason: '', idempotency_key: '' },
    capabilitiesLoading: false,
    saveNode: fn(),
    resetNodeForm: fn(),
    editNode: fn(),
    loadCapabilities: fn(),
    prepareOverride: fn(),
    createCalendarOverride: fn(),
    addCapability: fn(),
    removeCapability: fn(),
    saveCapabilities: fn(),
    showAdjustmentModal: false,
    adjustmentForm: { production_node_id: '', planned_start_at: '', reason: '', idempotency_key: '' },
    saveOperationAdjustment: fn(),
  }
}

describe('GanttChart production-node UX', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    ganttState = createState()
    mocks.updateScheduleOrderPriority.mockResolvedValue({})
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ''
    document.body.style.overflow = ''
    vi.restoreAllMocks()
  })

  it('delegates production-node management to the viewport workbench', () => {
    wrapper = mount(GanttChart, { attachTo: document.body })

    expect(document.body.querySelector('[data-test="production-node-workbench"]')).not.toBeNull()
    expect(wrapper.find('[data-test="legacy-node-manager-form"]').exists()).toBe(false)
    expect(document.body.querySelector('input[placeholder="节点编码，如 WELD-01"]')).toBeNull()
    expect(document.body.textContent).toContain('节点列表')
    expect(document.body.textContent).toContain('节点编辑')
    expect(document.body.textContent).toContain('工作日历')
    expect(document.body.textContent).toContain('能力限制')
  })

  it('renders production-node management, precise blocking, and locked-task evidence', () => {
    wrapper = mount(GanttChart)

    expect(wrapper.text()).toContain('生产节点管理')
    expect(wrapper.text()).toContain('WELD-01')
    expect(wrapper.text()).toContain('焊接-01')
    expect(wrapper.text()).toContain('没有满足能力要求的生产节点')
    expect(wrapper.text()).not.toContain('工序产线')
    expect(wrapper.text()).not.toContain('产线管理')
    expect(wrapper.text()).not.toContain('停机产线')
    expect(wrapper.find('[data-test="locked-task"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="blocked-code-NO_COMPATIBLE_NODE"]').text()).toContain('没有满足能力要求的生产节点')
  })

  async function openPriorityDrawer(order = { id: 12, order_no: '26091901', priority_level: 3, priority_version: 7 }) {
    ganttState.orderDrawerOpen.value = true
    ganttState.selectedScheduleOrder.value = order
    wrapper = mount(GanttChart, { attachTo: document.body })
    const orderDrawer = new DOMWrapper(document.body.querySelector('.schedule-order-drawer'))
    await orderDrawer.findAll('button').find(button => button.text() === '调整优先级').trigger('click')
    return new DOMWrapper(document.body.querySelector('.schedule-priority-drawer'))
  }

  it('renders complete drawer props without Vue warnings', () => {
    const warn = vi.spyOn(console, 'warn')
    const error = vi.spyOn(console, 'error')
    wrapper = mount(GanttChart, { attachTo: document.body })
    expect(warn).not.toHaveBeenCalled()
    expect(error).not.toHaveBeenCalled()
  })

  it('submits priority with its version once and refreshes both views after success', async () => {
    let resolveSave
    mocks.updateScheduleOrderPriority.mockReturnValue(new Promise(resolve => { resolveSave = resolve }))
    const drawer = await openPriorityDrawer()
    expect(ganttState.closeOrderDrawer).toHaveBeenCalledOnce()
    expect(document.body.querySelector('.schedule-order-drawer')).toBeNull()
    expect(drawer.get('select').element.value).toBe('3')
    expect(drawer.get('button[type="submit"]').element.disabled).toBe(true)

    await drawer.get('select').setValue('1')
    await drawer.get('input[type="checkbox"]').setValue(true)
    await drawer.get('textarea').setValue('  客户交期提前  ')
    await drawer.get('form').trigger('submit')
    await drawer.get('form').trigger('submit')

    expect(mocks.updateScheduleOrderPriority).toHaveBeenCalledExactlyOnceWith(12, {
      priority_level: 1,
      is_expedited: true,
      schedule_change_reason: '客户交期提前',
      expected_priority_version: 7,
    })
    expect(drawer.get('button[type="submit"]').element.disabled).toBe(true)
    expect(ganttState.load).not.toHaveBeenCalled()
    resolveSave({})
    await flushPromises()
    expect(document.body.querySelector('.schedule-priority-drawer')).toBeNull()
    expect(ganttState.load).toHaveBeenCalledOnce()
    expect(ganttState.loadCapacity).toHaveBeenCalledOnce()
    expect(mocks.showToast).toHaveBeenCalledWith('订单优先级已更新，已标记为待重新排程')
  })

  it('retains priority inputs after failure and allows retry with the legacy default version', async () => {
    mocks.updateScheduleOrderPriority.mockRejectedValueOnce(new Error('优先级版本已变化'))
    const drawer = await openPriorityDrawer({ id: 12, order_no: '26091901', priority: 2, is_expedited: 1 })
    expect(drawer.get('select').element.value).toBe('2')
    expect(drawer.get('input[type="checkbox"]').element.checked).toBe(true)
    await drawer.get('textarea').setValue('保留原因用于重试')
    await drawer.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.showToast).toHaveBeenCalledWith('优先级版本已变化', 'error')
    expect(document.body.querySelector('.schedule-priority-drawer')).not.toBeNull()
    expect(drawer.get('textarea').element.value).toBe('保留原因用于重试')
    expect(drawer.get('button[type="submit"]').element.disabled).toBe(false)
    expect(ganttState.load).not.toHaveBeenCalled()
    expect(ganttState.loadCapacity).not.toHaveBeenCalled()

    await drawer.get('form').trigger('submit')
    await flushPromises()
    expect(mocks.updateScheduleOrderPriority).toHaveBeenLastCalledWith(12, {
      priority_level: 2, is_expedited: true,
      schedule_change_reason: '保留原因用于重试', expected_priority_version: 1,
    })
    expect(document.body.querySelector('.schedule-priority-drawer')).toBeNull()
  })

  it('hides priority adjustment from users without schedule adjustment permission', () => {
    ganttState.canAdjustSchedules = false
    ganttState.orderDrawerOpen.value = true
    ganttState.selectedScheduleOrder.value = { id: 12, order_no: '26091901' }
    wrapper = mount(GanttChart, { attachTo: document.body })
    const orderDrawer = new DOMWrapper(document.body.querySelector('.schedule-order-drawer'))
    expect(orderDrawer.text()).not.toContain('调整优先级')
    expect(mocks.updateScheduleOrderPriority).not.toHaveBeenCalled()
  })

  it('preserves replan and operation actions when moving priority coordination out of the view', async () => {
    ganttState.orderDrawerOpen.value = true
    ganttState.selectedScheduleOrder.value = { id: 12, order_no: '26091901' }
    ganttState.selectedOrderOperations = [{ id: 501, process_id: 7, process_name: '焊接' }]
    wrapper = mount(GanttChart, { attachTo: document.body })
    const orderDrawer = new DOMWrapper(document.body.querySelector('.schedule-order-drawer'))
    await orderDrawer.findAll('button').find(button => button.text() === '模拟重排').trigger('click')
    expect(ganttState.replanOrderId.value).toBe(12)
    expect(ganttState.prepareDynamicReplan).toHaveBeenCalledWith(12)

    ganttState.viewMode.value = 'orders'
    await orderDrawer.findAll('button').find(button => button.text() === '查看工序进度').trigger('click')
    await orderDrawer.findAll('button').find(button => button.text() === '查看操作').trigger('click')
    await flushPromises()
    expect(ganttState.viewMode.value).toBe('operations')
    expect(mocks.updateScheduleOrderPriority).not.toHaveBeenCalled()
  })

  it.each([
    ['view-only', { view: true, nodes: false, capabilities: false, calendars: false }, true],
    ['node-only', { view: true, nodes: true, capabilities: false, calendars: false }, true],
    ['capability-only', { view: true, nodes: false, capabilities: true, calendars: false }, true],
    ['calendar-only', { view: true, nodes: false, capabilities: false, calendars: true }, true],
    ['no-access', { view: false, nodes: false, capabilities: false, calendars: false }, false],
  ])('applies the production-node permission matrix for %s users', (_label, permissions, visible) => {
    ganttState.showNodeMgr = false
    ganttState.canViewNodes = permissions.view
    ganttState.canManageNodes = permissions.nodes
    ganttState.canManageCapabilities = permissions.capabilities
    ganttState.canManageCalendars = permissions.calendars
    ganttState.productionNodeManager.permissions.canViewNodes = permissions.view
    ganttState.productionNodeManager.permissions.canManageNodes = permissions.nodes
    ganttState.productionNodeManager.permissions.canManageCapabilities = permissions.capabilities
    ganttState.productionNodeManager.permissions.canManageCalendars = permissions.calendars

    wrapper = mount(GanttChart)

    expect(wrapper.findAll('button').some(button => button.text().includes('生产节点管理'))).toBe(visible)
  })
})
