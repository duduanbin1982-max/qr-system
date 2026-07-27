import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CustomerList from '@/views/CustomerList.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listCustomers: vi.fn(),
  customerOrders: vi.fn(),
  createCustomer: vi.fn(),
  updateCustomer: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      customers: {
        listCustomers: mocks.listCustomers,
        customerOrders: mocks.customerOrders,
        createCustomer: mocks.createCustomer,
        updateCustomer: mocks.updateCustomer,
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
    mocks.createCustomer.mockReset()
    mocks.updateCustomer.mockReset()
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

  it('prevents duplicate submissions while a save is pending', async () => {
    mocks.permissions = new Set(['customers:view', 'customers:create'])
    let resolveCreate
    mocks.createCustomer.mockImplementation(() => new Promise(resolve => {
      resolveCreate = resolve
    }))
    const wrapper = mount(CustomerList)
    await flushPromises()
    await wrapper.find('button.btn-primary').trigger('click')
    await wrapper.find('input[placeholder="客户公司名称"]').setValue('并发客户')

    const firstSave = wrapper.vm.save()
    const secondSave = wrapper.vm.save()

    expect(mocks.createCustomer).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.saving).toBe(true)
    resolveCreate({ id: 1 })
    await Promise.all([firstSave, secondSave])
    await flushPromises()
    expect(wrapper.vm.saving).toBe(false)
  })

  it('uses server totals and resets pagination for searches', async () => {
    mocks.permissions = new Set(['customers:view'])
    mocks.listCustomers.mockResolvedValue({
      customers: [{ id: 21, name: '分页客户' }],
      total: 25,
      summary: { total: 25, with_orders: 2, with_contact: 13, with_email: 9 },
      available_tags: ['VIP', '重点'],
    })
    const wrapper = mount(CustomerList)
    await flushPromises()

    expect(wrapper.text()).toContain('客户总数')
    expect(wrapper.text()).toContain('25')
    await wrapper.vm.nextPage()
    await flushPromises()
    expect(mocks.listCustomers).toHaveBeenLastCalledWith({ page: 2, limit: 20 })

    await wrapper.find('input[placeholder="搜索名称/联系人/电话..."]').setValue('新关键词')
    wrapper.vm.searchAndLoad()
    await flushPromises()
    expect(mocks.listCustomers).toHaveBeenLastCalledWith({
      page: 1,
      limit: 20,
      keyword: '新关键词',
    })
  })
})
