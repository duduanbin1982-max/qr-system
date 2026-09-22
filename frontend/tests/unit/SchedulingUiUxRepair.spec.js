import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import OrderScheduleDrawer from '@/components/schedule/OrderScheduleDrawer.vue'
import ProductionNodeQueueBoard from '@/components/schedule/ProductionNodeQueueBoard.vue'
import { useGanttData } from '@/composables/gantt/useGanttData.js'

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
