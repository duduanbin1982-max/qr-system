import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useGantt } from '@/composables/useGantt.js'


const mocks = vi.hoisted(() => ({
  getScheduleGantt: vi.fn(),
  listProductionLines: vi.fn(),
  updateScheduleOrder: vi.fn(),
  batchShiftSchedule: vi.fn(),
  createProductionLine: vi.fn(),
  deleteProductionLine: vi.fn(),
  listProcessCapacityLines: vi.fn(),
  listOperationSchedules: vi.fn(),
  listCapacityOrders: vi.fn(),
  generateOrderOperationSchedule: vi.fn(),
  can: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      production: {
        getScheduleGantt: mocks.getScheduleGantt,
        listProductionLines: mocks.listProductionLines,
        updateScheduleOrder: mocks.updateScheduleOrder,
        batchShiftSchedule: mocks.batchShiftSchedule,
        createProductionLine: mocks.createProductionLine,
        deleteProductionLine: mocks.deleteProductionLine,
        listProcessCapacityLines: mocks.listProcessCapacityLines,
        listOperationSchedules: mocks.listOperationSchedules,
        listCapacityOrders: mocks.listCapacityOrders,
        generateOrderOperationSchedule: mocks.generateOrderOperationSchedule,
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
    min_date: '2026-07-01',
    max_date: '2026-08-31',
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
    mocks.can.mockImplementation(permission => permission !== 'settings:edit')
    mocks.getScheduleGantt.mockResolvedValue(response([]))
    mocks.listProductionLines.mockResolvedValue({ lines: [] })
    mocks.listProcessCapacityLines.mockResolvedValue({ lines: [] })
    mocks.listOperationSchedules.mockResolvedValue({ operations: [] })
    mocks.listCapacityOrders.mockResolvedValue({ orders: [] })
    mocks.updateScheduleOrder.mockResolvedValue({ ok: true })
  })

  it('filters orders by production line id and detects configured overloads', async () => {
    const orders = [
      { id: 1, status: 'producing', plan_start: '2026-07-01', plan_end: '2026-07-01', production_line_id: 1, production_line: '产线A', line_capacity: 1 },
      { id: 2, status: 'producing', plan_start: '2026-07-01', plan_end: '2026-07-01', production_line_id: 1, production_line: '产线A', line_capacity: 1 },
      { id: 3, status: 'producing', plan_start: '2026-07-01', plan_end: '2026-07-01', production_line_id: 2, production_line: '产线B', line_capacity: 10 },
    ]
    mocks.getScheduleGantt.mockResolvedValue(response(orders))
    mocks.listProductionLines.mockResolvedValue({
      lines: [
        { id: 1, name: '产线A', capacity_per_day: 1 },
        { id: 2, name: '产线B', capacity_per_day: 10 },
      ],
    })
    const harness = mountHarness()
    await flushPromises()

    harness.gantt.wsFilter.value = '1'

    expect(harness.gantt.filteredOrders.value.map(order => order.id)).toEqual([1, 2])
    expect(harness.gantt.dailyLoad.value).toEqual([
      expect.objectContaining({ lineId: 1, count: 2, capacity: 1 }),
    ])
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

  it('reloads data and lifecycle handlers after remounting', async () => {
    const first = mountHarness()
    await flushPromises()
    first.wrapper.unmount()

    const second = mountHarness()
    await flushPromises()

    expect(mocks.getScheduleGantt).toHaveBeenCalledTimes(2)
    expect(mocks.listProductionLines).toHaveBeenCalledTimes(2)
    second.wrapper.unmount()
  })

  it('loads operation schedules lazily and exposes process/line filters', async () => {
    mocks.listProcessCapacityLines.mockResolvedValue({
      lines: [{ id: 41, process_id: 7, process_name: '焊接', line_name: '焊接01线' }],
    })
    mocks.listOperationSchedules.mockResolvedValue({
      operations: [{ id: 9, process_id: 7, process_name: '焊接', process_line_id: 41, schedule_status: 'planned', planned_minutes: 90 }],
    })
    mocks.listCapacityOrders.mockResolvedValue({ orders: [{ id: 2, order_no: 'CAP-2', plan_start: '2026-07-01' }] })
    const harness = mountHarness()
    await flushPromises()

    await harness.gantt.setViewMode('operations')
    await flushPromises()

    expect(mocks.listProcessCapacityLines).toHaveBeenCalledTimes(1)
    expect(harness.gantt.processOptions.value).toEqual([{ id: 7, name: '焊接' }])
    expect(harness.gantt.filteredOperations.value).toHaveLength(1)
    expect(harness.gantt.capacitySummary.value).toEqual({ total: 1, planned: 1, blocked: 0, minutes: 90 })
    expect(harness.gantt.standardScopeLabel('route_version:product')).toBe('路线版本 · 产品专用')
    expect(harness.gantt.standardScopeLabel('unknown:scope')).toBe('unknown:scope')
    harness.gantt.capacityProcessFilter.value = '999'
    expect(harness.gantt.filteredOperations.value).toHaveLength(0)
    harness.wrapper.unmount()
  })
})
