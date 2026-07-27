import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CustomerList from '@/views/CustomerList.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listCustomers: vi.fn(),
  customerOrders: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      customers: {
        listCustomers: mocks.listCustomers,
        customerOrders: mocks.customerOrders,
      },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  can: vi.fn(permission => mocks.permissions.has(permission)),
}))

vi.mock('@/lib/store.js', () => ({ showToast: vi.fn() }))


describe('CustomerList order permissions', () => {
  beforeEach(() => {
    mocks.permissions = new Set()
    mocks.listCustomers.mockReset()
    mocks.customerOrders.mockReset()
    mocks.listCustomers.mockResolvedValue({
      customers: [{
        id: 1,
        name: '权限客户',
        order_count: 3,
        last_order_date: '2026-07-28 08:00:00',
      }],
      total: 1,
    })
  })

  it('hides order statistics and detail entry without orders:view', async () => {
    mocks.permissions = new Set(['customers:view'])
    const wrapper = mount(CustomerList)
    await flushPromises()

    expect(wrapper.find('[data-testid="customer-order-link"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('最近下单')
    expect(wrapper.text()).not.toContain('有订单')
  })

  it('shows order statistics and detail entry with orders:view', async () => {
    mocks.permissions = new Set(['customers:view', 'orders:view'])
    const wrapper = mount(CustomerList)
    await flushPromises()

    expect(wrapper.find('[data-testid="customer-order-link"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('最近下单')
    expect(wrapper.text()).toContain('有订单')
  })
})
