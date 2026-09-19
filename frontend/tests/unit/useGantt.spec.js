import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useGantt } from '@/composables/useGantt.js'


const mocks = vi.hoisted(() => ({
  getScheduleGantt: vi.fn(),
  updateScheduleOrder: vi.fn(),
  batchShiftSchedule: vi.fn(),
  listProductionNodes: vi.fn(),
  listScheduleCalendars: vi.fn(),
  listOperationSchedules: vi.fn(),
  listCapacityOrders: vi.fn(),
  generateOrderOperationSchedule: vi.fn(),
  dynamicReplanOrderSchedule: vi.fn(),
  autoPlanSchedule: vi.fn(),
  listScheduleDowntime: vi.fn(),
  createScheduleNodeDowntime: vi.fn(),
  cancelScheduleDowntime: vi.fn(),
  adjustScheduleItem: vi.fn(),
  lockScheduleItem: vi.fn(),
  unlockScheduleItem: vi.fn(),
  submitScheduleRevision: vi.fn(),
  approveScheduleRevision: vi.fn(),
  rejectScheduleRevision: vi.fn(),
  publishScheduleRevision: vi.fn(),
  can: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      production: {
        getScheduleGantt: mocks.getScheduleGantt,
        updateScheduleOrder: mocks.updateScheduleOrder,
        batchShiftSchedule: mocks.batchShiftSchedule,
        listProductionNodes: mocks.listProductionNodes,
        listScheduleCalendars: mocks.listScheduleCalendars,
        listOperationSchedules: mocks.listOperationSchedules,
        listCapacityOrders: mocks.listCapacityOrders,
        generateOrderOperationSchedule: mocks.generateOrderOperationSchedule,
        dynamicReplanOrderSchedule: mocks.dynamicReplanOrderSchedule,
        autoPlanSchedule: mocks.autoPlanSchedule,
        listScheduleDowntime: mocks.listScheduleDowntime,
        createScheduleNodeDowntime: mocks.createScheduleNodeDowntime,
        cancelScheduleDowntime: mocks.cancelScheduleDowntime,
        adjustScheduleItem: mocks.adjustScheduleItem,
        lockScheduleItem: mocks.lockScheduleItem,
        unlockScheduleItem: mocks.unlockScheduleItem,
        submitScheduleRevision: mocks.submitScheduleRevision,
        approveScheduleRevision: mocks.approveScheduleRevision,
        rejectScheduleRevision: mocks.rejectScheduleRevision,
        publishScheduleRevision: mocks.publishScheduleRevision,
      },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({ can: mocks.can }))
vi.mock('@/lib/store.js', () => ({ showToast: vi.fn() }))


function response(orders) {
  return {
    ok: true,
    orders,
    min_date: '2026-09-01',
    max_date: '2026-09-30',
    total: orders.length,
    has_more: false,
    stats: {
      total: orders.length,
      producing: orders.length,
      pending: 0,
      completed: 0,
    },
  }
}

function mountHarness() {
  let gantt
  const harness = defineComponent({
    setup() {
      gantt = useGantt()
      return () => h('div')
    },
  })
  return { wrapper: mount(harness), get gantt() { return gantt } }
}

describe('useGantt', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.can.mockReturnValue(true)
    mocks.getScheduleGantt.mockResolvedValue(response([]))
    mocks.listProductionNodes.mockResolvedValue({
      nodes: [
        { id: 41, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01' },
        { id: 42, process_id: 7, process_name: '焊接', node_code: 'WELD-02', node_name: '焊接-02' },
      ],
    })
    mocks.listScheduleCalendars.mockResolvedValue({ calendars: [{ id: 3, calendar_name: '九小时工作日历' }] })
    mocks.listOperationSchedules.mockResolvedValue({ operations: [] })
    mocks.listCapacityOrders.mockResolvedValue({ orders: [] })
    mocks.listScheduleDowntime.mockResolvedValue({ events: [] })
    mocks.createScheduleNodeDowntime.mockResolvedValue({ ok: true, event: { id: 1 } })
    mocks.cancelScheduleDowntime.mockResolvedValue({ ok: true, status: 'cancelled' })
    mocks.updateScheduleOrder.mockResolvedValue({ ok: true })
    mocks.autoPlanSchedule.mockResolvedValue({ ok: true, status: 'completed', queue_count: 2, failed_count: 0, orders: [] })
    mocks.adjustScheduleItem.mockResolvedValue({ ok: true })
    mocks.lockScheduleItem.mockResolvedValue({ ok: true })
    mocks.unlockScheduleItem.mockResolvedValue({ ok: true })
    mocks.submitScheduleRevision.mockResolvedValue({ ok: true })
    mocks.approveScheduleRevision.mockResolvedValue({ ok: true })
    mocks.rejectScheduleRevision.mockResolvedValue({ ok: true })
    mocks.publishScheduleRevision.mockResolvedValue({ ok: true })
  })

  it('loads production nodes and calendars without exposing line-based state', async () => {
    const harness = mountHarness()
    await flushPromises()

    expect(mocks.listProductionNodes).toHaveBeenCalledWith({ limit: 500 })
    expect(mocks.listScheduleCalendars).toHaveBeenCalledTimes(1)
    expect(harness.gantt.productionNodes.value).toHaveLength(2)
    expect(harness.gantt.nodesByProcess.value).toEqual([
      expect.objectContaining({ process_id: 7, process_name: '焊接' }),
    ])
    expect(harness.gantt).not.toHaveProperty('wsFilter')
    expect(harness.gantt).not.toHaveProperty('dailyLoad')
    expect(harness.gantt).not.toHaveProperty('productionLines')
    harness.wrapper.unmount()
  })

  it('loads every backend page before exposing the schedule', async () => {
    mocks.getScheduleGantt
      .mockResolvedValueOnce({ ...response([{ id: 2 }]), total: 2, has_more: true })
      .mockResolvedValueOnce({ ...response([{ id: 1 }]), total: 2, has_more: false })
    const harness = mountHarness()
    await flushPromises()

    expect(mocks.getScheduleGantt).toHaveBeenNthCalledWith(1, {
      status: 'active',
      limit: 200,
      offset: 0,
    })
    expect(mocks.getScheduleGantt).toHaveBeenNthCalledWith(2, {
      status: 'active',
      limit: 200,
      offset: 1,
    })
    expect(harness.gantt.orders.value.map(order => order.id)).toEqual([2, 1])
    harness.wrapper.unmount()
  })

  it('loads operation schedules and filters direct or split production-node assignments', async () => {
    mocks.listOperationSchedules.mockResolvedValue({
      operations: [
        {
          id: 9,
          process_id: 7,
          process_name: '焊接',
          production_node_id: 41,
          node_code: 'WELD-01',
          node_name: '焊接-01',
          schedule_status: 'planned',
          planned_minutes: 90,
        },
        {
          id: 10,
          process_id: 7,
          process_name: '焊接',
          schedule_status: 'blocked',
          blocked_code: 'NO_COMPATIBLE_NODE',
          allocations: [{ production_node_id: 42, node_code: 'WELD-02', node_name: '焊接-02', quantity: 3 }],
        },
      ],
    })
    mocks.listCapacityOrders.mockResolvedValue({ orders: [{ id: 2, order_no: 'CAP-2', plan_start: '2026-09-01' }] })
    const harness = mountHarness()
    await flushPromises()

    await harness.gantt.setViewMode('operations')
    await flushPromises()

    expect(harness.gantt.processOptions.value).toEqual([{ id: 7, name: '焊接' }])
    expect(harness.gantt.capacitySummary.value).toEqual({ total: 2, planned: 1, blocked: 1, minutes: 90 })
    expect(harness.gantt.nodeLabel(harness.gantt.operationSchedules.value[0])).toBe('WELD-01 · 焊接-01')
    expect(harness.gantt.allocationLabel(harness.gantt.operationSchedules.value[1].allocations[0])).toBe('WELD-02 · 焊接-02 × 3')
    expect(harness.gantt.blockedMessage({ blocked_code: 'NO_COMPATIBLE_NODE' })).toBe('没有满足能力要求的生产节点')

    harness.gantt.capacityNodeFilter.value = '42'
    expect(harness.gantt.filteredOperations.value.map(row => row.id)).toEqual([10])
    harness.gantt.capacityProcessFilter.value = '999'
    expect(harness.gantt.filteredOperations.value).toHaveLength(0)
    harness.wrapper.unmount()
  })

  it('creates node downtime using production_node_id and cancels it', async () => {
    const harness = mountHarness()
    await flushPromises()
    await harness.gantt.setViewMode('operations')
    await flushPromises()

    harness.gantt.downtimeForm.value = {
      production_node_id: 41,
      start_at: '2026-09-01T08:00',
      end_at: '2026-09-01T09:30',
      reason: '设备检修',
    }
    await harness.gantt.createDowntime()

    expect(mocks.createScheduleNodeDowntime).toHaveBeenCalledWith({
      production_node_id: 41,
      start_at: '2026-09-01T08:00',
      end_at: '2026-09-01T09:30',
      reason: '设备检修',
    })
    expect(mocks.createScheduleNodeDowntime.mock.calls[0][0]).not.toHaveProperty('process_line_id')
    expect(mocks.listScheduleDowntime).toHaveBeenCalledTimes(2)

    await harness.gantt.cancelDowntime({ id: 12 })
    expect(mocks.cancelScheduleDowntime).toHaveBeenCalledWith(12)
    harness.wrapper.unmount()
  })

  it('adjusts, locks, and unlocks immutable revision items without line fields', async () => {
    const harness = mountHarness()
    await flushPromises()
    await harness.gantt.setViewMode('operations')

    const row = {
      revision_item_id: 901,
      revision_item_row_version: 3,
      production_node_id: 41,
      planned_start_at: '2026-09-01 08:00:00',
    }
    expect(harness.gantt.prepareAdjustment(row)).toBe(true)
    harness.gantt.adjustmentForm.value.reason = '改用可用焊接节点'
    harness.gantt.adjustmentForm.value.idempotency_key = 'adjust-901-1'
    await harness.gantt.saveOperationAdjustment()

    expect(mocks.adjustScheduleItem).toHaveBeenCalledWith(901, {
      production_node_id: 41,
      planned_start_at: '2026-09-01T08:00',
      row_version: 3,
      reason: '改用可用焊接节点',
      idempotency_key: 'adjust-901-1',
    })
    expect(mocks.adjustScheduleItem.mock.calls[0][1]).not.toHaveProperty('process_line_id')

    await harness.gantt.lockOperation(row, '生产主管锁定')
    await harness.gantt.unlockOperation(row, '停机解除后解锁')
    expect(mocks.lockScheduleItem).toHaveBeenCalledWith(901, expect.objectContaining({ reason: '生产主管锁定' }))
    expect(mocks.unlockScheduleItem).toHaveBeenCalledWith(901, expect.objectContaining({ reason: '停机解除后解锁' }))
    harness.wrapper.unmount()
  })

  it('runs schedule revision lifecycle commands with schedule_revision_id', async () => {
    const harness = mountHarness()
    await flushPromises()
    await harness.gantt.setViewMode('operations')
    const row = { schedule_revision_id: 77 }

    await harness.gantt.submitRevision(row, '提交复核')
    await harness.gantt.approveRevision(row, '独立批准')
    await harness.gantt.rejectRevision(row, '节点冲突')
    await harness.gantt.publishRevision(row)

    expect(mocks.submitScheduleRevision).toHaveBeenCalledWith(77, expect.objectContaining({ reason: '提交复核' }))
    expect(mocks.approveScheduleRevision).toHaveBeenCalledWith(77, expect.objectContaining({ reason: '独立批准' }))
    expect(mocks.rejectScheduleRevision).toHaveBeenCalledWith(77, expect.objectContaining({ reason: '节点冲突' }))
    expect(mocks.publishScheduleRevision).toHaveBeenCalledWith(77, {})
    harness.wrapper.unmount()
  })

  it('normalizes deadline risk levels and exposes delay summaries for the gantt', async () => {
    mocks.getScheduleGantt.mockResolvedValue(response([
      { id: 11, risk_level: 'high', delay_minutes: 150, risk_reason: '预计完成时间晚于交期' },
      { id: 12, risk: 'overdue', delay_minutes: 60 },
      { id: 13, risk_level: 'none', delay_minutes: 0 },
    ]))
    const harness = mountHarness()
    await flushPromises()

    expect(harness.gantt.riskSummary.value).toMatchObject({ high: 1, overdue: 1, none: 1, delayed: 2, totalDelayMinutes: 210 })
    expect(harness.gantt.formatRiskMinutes(150)).toBe('2 小时 30 分钟')
    harness.wrapper.unmount()
  })

  it('runs the priority queue automatic plan through the production facade', async () => {
    const harness = mountHarness()
    await flushPromises()

    harness.gantt.prepareAutoPlan()
    harness.gantt.autoPlanStartDate.value = '2026-09-14'
    harness.gantt.autoPlanLimit.value = 25
    harness.gantt.autoPlanKey.value = 'auto-plan-ui-test-001'
    const result = await harness.gantt.runAutoPlan()

    expect(mocks.autoPlanSchedule).toHaveBeenCalledWith({
      start_date: '2026-09-14',
      auto_plan_key: 'auto-plan-ui-test-001',
      limit: 25,
    })
    expect(result).toMatchObject({ status: 'completed', queue_count: 2 })
    expect(mocks.listOperationSchedules).toHaveBeenCalledTimes(1)
    harness.wrapper.unmount()
  })

  it('rejects invalid downtime and automatic-plan limits before sending requests', async () => {
    const harness = mountHarness()
    await flushPromises()
    harness.gantt.downtimeForm.value = {
      production_node_id: 41,
      start_at: '2026-09-01T10:00',
      end_at: '2026-09-01T09:00',
      reason: '时间错误',
    }
    await harness.gantt.createDowntime()
    expect(mocks.createScheduleNodeDowntime).not.toHaveBeenCalled()

    harness.gantt.prepareAutoPlan()
    harness.gantt.autoPlanLimit.value = 1001
    await harness.gantt.runAutoPlan()
    expect(mocks.autoPlanSchedule).not.toHaveBeenCalled()
    harness.wrapper.unmount()
  })
})
