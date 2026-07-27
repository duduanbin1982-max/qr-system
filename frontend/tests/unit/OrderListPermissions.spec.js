import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import OrderList from '@/views/OrderList.vue'


const facade = vi.hoisted(() => ({ current: null }))

vi.mock('@/composables/useOrder.js', () => ({
  useOrder: () => facade.current,
}))


function orderState(permissionOverrides = {}) {
  const order = {
    id: 1,
    order_no: 'ORDER-PERM-001',
    customer: '测试客户',
    product_name: '测试产品',
    product_code: 'TEST-001',
    quantity: 10,
    completed: 0,
    scrapped: 0,
    status: 'pending',
    processes: [],
  }
  return {
    total: 1,
    pendingCount: 1,
    producingCount: 0,
    completedCount: 0,
    archiveFilter: 'active',
    filterStatus: '',
    filterCustomer: '',
    customers: [],
    searchKeyword: '',
    orders: [order],
    expandedId: null,
    page: 1,
    limit: 20,
    statusMap: { pending: { label: '待生产', cls: 'badge-pending' } },
    canCreate: false,
    canEdit: false,
    canDelete: false,
    canScanView: false,
    canReport: false,
    showModal: false,
    modalEdit: false,
    showCompletionFocus: false,
    showFocusExceptionModal: false,
    showReworkModal: false,
    showQrPrint: false,
    showTrash: false,
    progressOrder: null,
    pct: () => 0,
    scrapPct: () => 0,
    isCompletedOrder: item => item.status === 'completed',
    searchAndLoad: vi.fn(),
    archiveChange: vi.fn(),
    statusChange: vi.fn(),
    customerChange: vi.fn(),
    debouncedSearch: vi.fn(),
    openCompletionFocus: vi.fn(),
    openAdd: vi.fn(),
    loadTrash: vi.fn(),
    toggleExpandAndLoad: vi.fn(),
    openProgress: vi.fn(),
    openEdit: vi.fn(),
    openQrPrint: vi.fn(),
    openRework: vi.fn(),
    del: vi.fn(),
    reopenOrder: vi.fn(),
    prevPage: vi.fn(),
    nextPage: vi.fn(),
    ...permissionOverrides,
  }
}


describe('OrderList action permissions', () => {
  it('hides mutation, QR, and report actions without their permissions', () => {
    facade.current = orderState()
    const wrapper = mount(OrderList)

    expect(wrapper.text()).not.toContain('新建订单')
    expect(wrapper.find('[title="编辑"]').exists()).toBe(false)
    expect(wrapper.find('[title="打印二维码"]').exists()).toBe(false)
    expect(wrapper.find('[title="申请返工"]').exists()).toBe(false)
    expect(wrapper.find('[title="删除"]').exists()).toBe(false)
    expect(wrapper.find('[title="工件进度"]').exists()).toBe(true)
  })

  it('shows each action when its matching permission is granted', () => {
    facade.current = orderState({
      canCreate: true,
      canEdit: true,
      canDelete: true,
      canScanView: true,
      canReport: true,
    })
    const wrapper = mount(OrderList)

    expect(wrapper.text()).toContain('新建订单')
    expect(wrapper.find('[title="编辑"]').exists()).toBe(true)
    expect(wrapper.find('[title="打印二维码"]').exists()).toBe(true)
    expect(wrapper.find('[title="申请返工"]').exists()).toBe(true)
    expect(wrapper.find('[title="删除"]').exists()).toBe(true)
  })
})
