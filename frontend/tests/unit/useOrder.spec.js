import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useOrder } from '@/composables/useOrder.js'


const mocks = vi.hoisted(() => ({
  listOrders: vi.fn(),
  listCustomers: vi.fn(),
  listProducts: vi.fn(),
  listProcessRoutes: vi.fn(),
  listProductionLines: vi.fn(),
  listOrderMaterials: vi.fn(),
  listMaterials: vi.fn(),
  listProcesses: vi.fn(),
  updateOrder: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      orders: { listOrders: mocks.listOrders, updateOrder: mocks.updateOrder },
      customers: { listCustomers: mocks.listCustomers },
      products: {
        listProducts: mocks.listProducts,
        listOrderMaterials: mocks.listOrderMaterials,
      },
      materials: { listMaterials: mocks.listMaterials },
      processes: { listProcesses: mocks.listProcesses },
      processRoutes: { listProcessRoutes: mocks.listProcessRoutes },
      production: { listProductionLines: mocks.listProductionLines },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  auth: { user: null },
  can: vi.fn(() => true),
}))

vi.mock('@/lib/store.js', () => ({ showToast: vi.fn() }))
vi.mock('@/composables/useQrcode.js', () => ({
  useQrcode: () => ({ printQr: vi.fn() }),
}))


describe('useOrder facade', () => {
  it('loads query data and preserves the page-facing contract', async () => {
    mocks.listOrders.mockResolvedValue({ orders: [{ id: 1 }], total: 1 })
    mocks.listCustomers.mockResolvedValue({ customers: [] })
    mocks.listProducts.mockResolvedValue({ products: [] })
    mocks.listProcessRoutes.mockResolvedValue({ routes: [] })
    mocks.listProductionLines.mockResolvedValue({ lines: [] })

    let order
    const harness = defineComponent({
      setup() {
        order = useOrder()
        return () => h('div')
      },
    })

    mount(harness)
    await flushPromises()

    expect(mocks.listOrders).toHaveBeenCalledWith({ page: 1, limit: 20, archive: 'active' })
    expect(order.orders.value).toEqual([{ id: 1 }])
    expect(order).toEqual(expect.objectContaining({
      openAdd: expect.any(Function),
      openEdit: expect.any(Function),
      addOrderMaterial: expect.any(Function),
      handleAttachmentUpload: expect.any(Function),
      openRework: expect.any(Function),
      openProgress: expect.any(Function),
      openCompletionFocus: expect.any(Function),
      loadTrash: expect.any(Function),
      uploadInputRef: expect.any(Object),
    }))
  })

  it('coordinates editor and material state through the facade', async () => {
    mocks.listOrders.mockResolvedValue({ orders: [], total: 0 })
    mocks.listCustomers.mockResolvedValue({ customers: [] })
    mocks.listProducts.mockResolvedValue({
      products: [{ id: 5, product_code: 'P-001', weight: 2.5, route_id: 8 }],
    })
    mocks.listProcessRoutes.mockResolvedValue({ routes: [{ id: 8, name: '标准路线' }] })
    mocks.listProductionLines.mockResolvedValue({ lines: [] })
    mocks.listOrderMaterials.mockResolvedValue({ materials: [{ id: 12 }] })
    mocks.listMaterials.mockResolvedValue({ materials: [{ id: 20 }] })
    mocks.listProcesses.mockResolvedValue({ processes: [{ id: 30, name: '下料' }] })

    let order
    const harness = defineComponent({
      setup() {
        order = useOrder()
        return () => h('div')
      },
    })

    mount(harness)
    await flushPromises()
    await order.openEdit({
      id: 9,
      status: 'producing',
      order_no: 'ORD-009',
      product_code: 'P-001',
      product_name: '测试产品',
      route_id: 8,
      quantity: 10,
    })

    expect(mocks.listOrderMaterials).toHaveBeenCalledWith(9)
    expect(order.modalId.value).toBe(9)
    expect(order.routeSearch.value).toBe('标准路线')
    expect(order.orderMaterials.value).toEqual([{ id: 12 }])
    expect(order.orderMatForm.value).toEqual(expect.objectContaining({
      quantity_per_unit: 2.5,
      process_id: 30,
    }))
  })

  it('submits a cleared route explicitly when editing', async () => {
    mocks.listOrders.mockResolvedValue({ orders: [], total: 0 })
    mocks.listCustomers.mockResolvedValue({ customers: [] })
    mocks.listProducts.mockResolvedValue({ products: [] })
    mocks.listProcessRoutes.mockResolvedValue({ routes: [{ id: 8, name: '标准路线' }] })
    mocks.listProductionLines.mockResolvedValue({ lines: [] })
    mocks.listOrderMaterials.mockResolvedValue({ materials: [] })
    mocks.listMaterials.mockResolvedValue({ materials: [] })
    mocks.listProcesses.mockResolvedValue({ processes: [] })
    mocks.updateOrder.mockResolvedValue({ message: '更新成功' })

    let order
    const harness = defineComponent({
      setup() {
        order = useOrder()
        return () => h('div')
      },
    })

    mount(harness)
    await flushPromises()
    await order.openEdit({
      id: 9,
      status: 'pending',
      order_no: 'ORD-009',
      product_name: '测试产品',
      route_id: 8,
      quantity: 10,
    })
    order.form.value.route_id = ''
    order.routeSearch.value = ''

    await order.save()

    expect(mocks.updateOrder).toHaveBeenCalledWith(
      9,
      expect.objectContaining({ route_id: null }),
    )
  })
})
