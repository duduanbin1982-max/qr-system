import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import OrderScheduleDrawer from '@/components/schedule/OrderScheduleDrawer.vue'
import ProductionNodeQueueBoard from '@/components/schedule/ProductionNodeQueueBoard.vue'
import ScheduleCommandDrawer from '@/components/schedule/ScheduleCommandDrawer.vue'
import SchedulePriorityDrawer from '@/components/schedule/SchedulePriorityDrawer.vue'
import { useGanttData } from '@/composables/gantt/useGanttData.js'
import { scheduleSegments } from '@/composables/gantt/useScheduleSegments.js'

const apiMocks = vi.hoisted(() => ({
  getScheduleGantt: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { production: { getScheduleGantt: apiMocks.getScheduleGantt } } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: apiMocks.showToast }))

describe('scheduling UI/UX repair phase', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    document.body.style.overflow = ''
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('opens order details as a viewport-fixed drawer and restores focus state on close', async () => {
    const wrapper = mount(OrderScheduleDrawer, {
      attachTo: document.body,
      props: { open: true, order: { id: 1, order_no: '26092201', product_code: 'SB121' } },
    })
    await flushPromises()
    expect(document.body.querySelector('.schedule-order-drawer')).not.toBeNull()
    expect(document.body.style.overflow).toBe('hidden')
    await wrapper.setProps({ open: false })
    expect(document.body.style.overflow).toBe('')
    wrapper.unmount()
  })

  it('renders the three-column process/node/timeline queue workbench', async () => {
    const wrapper = mount(ProductionNodeQueueBoard, {
      props: {
        nodes: [
          { id: 1, process_id: 7, process_name: '焊接', node_code: 'WELD-01', capacity_minutes: 540 },
          { id: 2, process_id: 7, process_name: '焊接', node_code: 'WELD-02', capacity_minutes: 540 },
        ],
        operations: [{ id: 11, order_id: 5, order_no: '26092201', process_id: 7, process_name: '焊接', production_node_id: 1, planned_start_at: '2026-09-22 08:00:00' }],
        orders: [{ id: 5, order_no: '26092201' }],
      },
    })
    expect(wrapper.find('[aria-label="工序列表"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="生产节点列表"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="节点时间轴"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('26092201')
  })

  it('normalizes node segments without losing risk, blocking, standard, and actual facts', () => {
    const rows = scheduleSegments({
      id: 11,
      order_id: 5,
      order_no: '26092201',
      process_id: 7,
      process_name: '焊接',
      status: 'blocked',
      blocked_code: 'NO_COMPATIBLE_NODE',
      blocked_reason: '没有符合能力要求的生产节点',
      risk_level: 'high',
      actual_start_at: '2026-09-22 08:00:00',
      actual_last_report_at: '2026-09-22 09:00:00',
      standard_match_scope: 'route_version:generic',
      segments: [
        { id: 1, production_node_id: 41, node_code: 'WELD-01', segment_start_at: '2026-09-22 10:00:00', segment_end_at: '2026-09-22 11:00:00', occupied_minutes: 60, quantity: 2 },
        { id: 2, production_node_id: 42, node_code: 'WELD-02', segment_start_at: '2026-09-22 11:00:00', segment_end_at: '2026-09-22 12:00:00', occupied_minutes: 60, quantity: 3 },
      ],
    })

    expect(rows).toHaveLength(2)
    expect(rows.map(row => row.production_node_id)).toEqual([41, 42])
    expect(rows.map(row => row.quantity)).toEqual([2, 3])
    expect(rows[0]).toMatchObject({
      blocked_code: 'NO_COMPATIBLE_NODE',
      blocked_reason: '没有符合能力要求的生产节点',
      risk_level: 'high',
      actual_last_report_at: '2026-09-22 09:00:00',
      standard_match_scope: 'route_version:generic',
    })
  })

  it('shows complete standard and node snapshots in the order drawer with controlled priority action', async () => {
    const wrapper = mount(OrderScheduleDrawer, {
      attachTo: document.body,
      global: { stubs: { teleport: true } },
      props: {
        open: true,
        canAdjustPriority: true,
        order: { id: 5, order_no: '26092201', priority_level: 1, is_expedited: true },
        operations: [{
          id: 11,
          process_name: '焊接',
          standard_match_scope: 'route_version:generic',
          node_code_snapshot: 'WELD-01',
          node_name_snapshot: '焊接节点 01',
          actual_start_at: '2026-09-22 08:00:00',
          actual_last_report_at: '2026-09-22 09:00:00',
        }],
      },
    })
    await wrapper.findAll('.schedule-order-drawer__tabs button').find(button => button.text().includes('工序进度')).trigger('click')
    expect(document.body.textContent).toContain('路线版本 · 通用')
    expect(document.body.textContent).toContain('WELD-01 · 焊接节点 01')
    expect(document.body.textContent).toContain('最近报工')
    await wrapper.findAll('.schedule-order-drawer__tabs button').find(button => button.text().includes('概览')).trigger('click')
    expect(document.body.textContent).toContain('P1 · 加急')
    expect(document.body.textContent).toContain('调整优先级')
    wrapper.unmount()
  })

  it('closes the command drawer with Escape and restores page scrolling', async () => {
    const wrapper = mount(ScheduleCommandDrawer, {
      attachTo: document.body,
      props: { open: true, form: { plan_start: '2026-09-22', plan_end: '2026-09-23' } },
    })
    await flushPromises()
    expect(document.body.style.overflow).toBe('hidden')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ open: false })
    expect(document.body.style.overflow).toBe('')
    wrapper.unmount()
  })

  it('requires a reason and emits the controlled priority payload', async () => {
    const wrapper = mount(SchedulePriorityDrawer, {
      attachTo: document.body,
      global: { stubs: { teleport: true } },
      props: { open: true, order: { id: 5, order_no: '26092201', priority_level: 3 } },
    })
    await wrapper.get('select').setValue('1')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('textarea').setValue('客户交期提前')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')?.[0]?.[0]).toEqual({
      priority_level: 1,
      is_expedited: true,
      schedule_change_reason: '客户交期提前',
    })
    wrapper.unmount()
  })

  it('filters orders and persists named filter presets locally', async () => {
    apiMocks.getScheduleGantt.mockResolvedValue({
      orders: [
        { id: 1, order_no: '26092201', product_code: 'SB121', status: 'producing', priority_level: 1, deadline: '2026-09-30', risk_level: 'high' },
        { id: 2, order_no: '26092202', product_code: 'SB81', status: 'pending', priority_level: 3, deadline: '2026-10-10', risk_level: 'none' },
      ],
      has_more: false,
      min_date: '2026-09-22',
      max_date: '2026-10-10',
      stats: { total: 2, producing: 1, pending: 1, completed: 0 },
    })
    const state = useGanttData()
    await state.load()
    state.orderKeyword.value = '26092201'
    expect(state.filteredOrders.value).toHaveLength(1)
    expect(state.filteredOrders.value[0].product_code).toBe('SB121')
    state.orderKeyword.value = ''
    state.priorityFilter.value = '1'
    expect(state.filteredOrders.value.map(order => order.order_no)).toEqual(['26092201'])
    state.orderKeyword.value = '26092201'
    expect(state.saveFilter('高风险焊接订单')).toBe(true)
    expect(JSON.parse(localStorage.getItem('schedule-gantt-saved-filters-v1'))[0].name).toBe('高风险焊接订单')
    state.resetFilters()
    state.applySavedFilter('高风险焊接订单')
    expect(state.orderKeyword.value).toBe('26092201')
  })
})
