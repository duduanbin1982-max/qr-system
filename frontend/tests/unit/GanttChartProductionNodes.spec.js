import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import GanttChart from '@/views/GanttChart.vue'


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
    viewMode: 'operations',
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
    setViewMode: fn(),
    setScheduleScope: fn(),
    zoomOut: fn(),
    zoomIn: fn(),
    exportImage: fn(),
    capacityProcessFilter: '',
    capacityNodeFilter: '',
    processOptions: [{ id: 7, name: '焊接' }],
    capacityNodes: [node],
    capacitySummary: { total: 1, planned: 0, blocked: 1, minutes: 0 },
    generationOrderId: '',
    generationStartDate: '2026-09-19',
    capacityOrders: [],
    prepareGeneration: fn(),
    generateSchedule: fn(),
    replanOrderId: '',
    replanStartAt: '2026-09-19T08:00',
    replanReason: '',
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
    loading: false,
    filteredOrders: [],
    selectedOrderIds: [],
    showEditModal: false,
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
    ganttState = createState()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ''
    document.body.style.overflow = ''
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
