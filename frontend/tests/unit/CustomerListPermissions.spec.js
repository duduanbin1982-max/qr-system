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

  it('clears stale orders and ignores superseded detail requests', async () => {
    mocks.permissions = new Set(['customers:view', 'orders:view'])
    let resolveFirst
    let resolveSecond
    mocks.customerOrders.mockImplementation(id => new Promise(resolve => {
      if (id === 1) resolveFirst = resolve
      else resolveSecond = resolve
    }))
    const wrapper = mount(CustomerList)
    await flushPromises()

    const firstRequest = wrapper.vm.viewDetail({ id: 1, name: '客户一' })
    const secondRequest = wrapper.vm.viewDetail({ id: 2, name: '客户二' })
    expect(wrapper.vm.detailOrders).toEqual([])
    resolveSecond({ orders: [{ id: 22, order_no: 'ORDER-002' }], total: 1 })
    await secondRequest
    expect(wrapper.vm.detailOrders).toEqual([{ id: 22, order_no: 'ORDER-002' }])

    resolveFirst({ orders: [{ id: 11, order_no: 'ORDER-001' }], total: 1 })
    await firstRequest
    expect(wrapper.vm.detailOrders).toEqual([{ id: 22, order_no: 'ORDER-002' }])
  })

  it('ignores a pending detail response after the modal closes', async () => {
    mocks.permissions = new Set(['customers:view', 'orders:view'])
    let resolveRequest
    mocks.customerOrders.mockImplementation(() => new Promise(resolve => {
      resolveRequest = resolve
    }))
    const wrapper = mount(CustomerList)
    await flushPromises()

    const request = wrapper.vm.viewDetail({ id: 1, name: '关闭测试客户' })
    wrapper.vm.closeDetail()
    resolveRequest({ orders: [{ id: 11, order_no: 'ORDER-001' }], total: 1 })
    await request

    expect(wrapper.vm.showDetail).toBe(false)
    expect(wrapper.vm.detail).toBe(null)
    expect(wrapper.vm.detailOrders).toEqual([])
  })

  it('shows detail failures and uses total to stop pagination', async () => {
    mocks.permissions = new Set(['customers:view', 'orders:view'])
    mocks.customerOrders
      .mockRejectedValueOnce(new Error('订单网络失败'))
      .mockResolvedValueOnce({ orders: Array.from({ length: 10 }, (_, index) => ({ id: index + 1 })), total: 11 })
      .mockResolvedValueOnce({ orders: [{ id: 11 }], total: 11 })
    const wrapper = mount(CustomerList)
    await flushPromises()

    await wrapper.vm.viewDetail({ id: 1, name: '详情客户' })
    await flushPromises()
    expect(wrapper.text()).toContain('订单网络失败')
    expect(wrapper.text()).not.toContain('暂无订单记录')

    await wrapper.vm.loadDetailOrders(1)
    await flushPromises()
    expect(wrapper.vm.detailTotal).toBe(11)
    wrapper.vm.detailNextPage()
    await flushPromises()
    expect(mocks.customerOrders).toHaveBeenLastCalledWith(1, { page: 2, limit: 10 })
    expect(wrapper.vm.detailPage).toBe(2)
    wrapper.vm.detailNextPage()
    expect(wrapper.vm.detailPage).toBe(2)
  })
})
