import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import InventoryList from '@/views/InventoryList.vue'
import { useInventoryProductGroups } from '@/composables/inventory/useInventoryProductGroups.js'

const mocks = vi.hoisted(() => ({
  inventoryCapabilities: vi.fn(),
  inventoryFilterOptions: vi.fn(),
  listInventory: vi.fn(),
  listProductGroups: vi.fn(),
  inventoryStats: vi.fn(),
  listOrders: vi.fn(),
  showToast: vi.fn(),
}))

// Keep both composables and every page component real; only replace the API
// boundary so order/product responses can be deliberately different.
vi.mock('@/lib/api.js', () => ({
  api: { domains: {
    inventory: {
      inventoryCapabilities: mocks.inventoryCapabilities,
      inventoryFilterOptions: mocks.inventoryFilterOptions,
      listInventory: mocks.listInventory,
      listProductGroups: mocks.listProductGroups,
      inventoryStats: mocks.inventoryStats,
    },
    orders: { listOrders: mocks.listOrders },
  } },
}))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

const orderSummary = { total_items: 12, total_quantity: 96, total_value: 12500, today_in: 10, today_out: 4, low_stock: 3 }
const productSummary = { total_items: 7, total_quantity: 71, total_value: 7100, today_in: 0, today_out: 2, low_stock: 2 }
const lowOrderSummary = { total_items: 3, total_quantity: 6, total_value: 120, today_in: 0, today_out: 1, low_stock: 3 }
const lowProductSummary = { total_items: 2, total_quantity: 5, total_value: 100, today_in: 0, today_out: 0, low_stock: 2 }
const wrappers = []

function mountTracked(component) {
  const wrapper = mount(component)
  wrappers.push(wrapper)
  return wrapper
}

function expectSummary(wrapper, summary) {
  expect(wrapper.findAll('.inventory-summary-bar .s-val').map(item => item.text())).toEqual([
    String(summary.total_items),
    String(summary.total_quantity),
    summary.total_value.toLocaleString(),
    String(summary.today_in),
    String(summary.today_out),
    String(summary.low_stock),
  ])
  expect(wrapper.find('.summary-item-action').attributes('aria-label')).toBe(`筛选低库存，共 ${summary.low_stock} 项`)
}

describe('inventory view behavior', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mocks.inventoryCapabilities.mockResolvedValue({ product_query_enabled: true })
    mocks.inventoryFilterOptions.mockResolvedValue({
      specifications: [{ value: '标准', inventory_count: 7 }],
      locations: [{ value: '东库', inventory_count: 7 }],
      quality_statuses: [{ value: 'qualified', inventory_count: 7 }],
    })
    mocks.listInventory.mockResolvedValue({
      items: [{ id: 1, product_model: 'ORDER-1', product_name: '订单库存', quantity: 8, available_quantity: 8 }],
      total: 12,
    })
    mocks.listProductGroups.mockResolvedValue({
      items: [{ product_id: 1, product_code: 'PRODUCT-1', product_name: '产品库存', quantity: 9, available_quantity: 9 }],
      total: 7,
    })
    mocks.listOrders.mockResolvedValue({ orders: [] })
    mocks.inventoryStats.mockImplementation((params = {}) => {
      const product = params.view === 'product'
      return Promise.resolve(params.low_stock === '1'
        ? (product ? lowProductSummary : lowOrderSummary)
        : (product ? productSummary : orderSummary))
    })
  })

  afterEach(() => {
    wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  })

  it('exposes a working setViewMode action that persists changes and loads product data', async () => {
    let product
    mountTracked({
      setup() {
        product = useInventoryProductGroups()
        return {}
      },
      template: '<div />',
    })
    await flushPromises()
    expect(product.state.viewMode.value).toBe('order')
    expect(mocks.listProductGroups).not.toHaveBeenCalled()
    expect(product.actions.setViewMode).toEqual(expect.any(Function))

    product.actions.setViewMode('product')
    await flushPromises()

    expect(product.state.viewMode.value).toBe('product')
    expect(localStorage.getItem('inventory-workbench:v1:view')).toBe('product')
    expect(mocks.listProductGroups).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ page: 1, limit: 200 }))
    expect(mocks.inventoryStats).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ view: 'product' }))
    expect(product.state.summary.value).toEqual(productSummary)

    product.actions.setViewMode('order')
    await flushPromises()
    expect(product.state.viewMode.value).toBe('order')
    expect(localStorage.getItem('inventory-workbench:v1:view')).toBe('order')
    expect(mocks.listProductGroups).toHaveBeenCalledTimes(1)
  })

  it('renders each view\'s six summary values when switching order → product → order', async () => {
    const wrapper = mountTracked(InventoryList)
    await flushPromises()
    expectSummary(wrapper, orderSummary)
    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe('按订单')
    expect(wrapper.find('.inventory-order-table').exists()).toBe(true)

    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()

    expectSummary(wrapper, productSummary)
    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe('按产品编码')
    expect(wrapper.find('.inventory-product-table').exists()).toBe(true)
    expect(wrapper.find('.inventory-order-table').exists()).toBe(false)
    expect(localStorage.getItem('inventory-workbench:v1:view')).toBe('product')

    await wrapper.findAll('[role="tab"]')[0].trigger('click')
    await flushPromises()

    expectSummary(wrapper, orderSummary)
    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe('按订单')
    expect(wrapper.find('.inventory-order-table').exists()).toBe(true)
    expect(localStorage.getItem('inventory-workbench:v1:view')).toBe('order')
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it.each(['order', 'product'])('filters only the %s view when its low-stock summary card is clicked', async (mode) => {
    const wrapper = mountTracked(InventoryList)
    await flushPromises()
    if (mode === 'product') {
      await wrapper.findAll('[role="tab"]')[1].trigger('click')
      await flushPromises()
    }
    const workbench = wrapper.find(mode === 'product'
      ? '.inventory-product-card .inventory-filter-workbench'
      : '.inventory-order-header .inventory-filter-workbench')
    await workbench.find('.inventory-filter-keyword input').setValue('待出库')
    await workbench.findAll('.inventory-filter-field select')[0].setValue('东库')
    await workbench.findAll('.inventory-filter-field select')[1].setValue('qualified')
    await workbench.find('.inventory-spec-option input').setValue(true)
    vi.clearAllMocks()

    await wrapper.find('.summary-item-action').trigger('click')
    await flushPromises()

    const sharedFilters = { low_stock: '1', keyword: '待出库', location: '东库', quality_status: 'qualified' }
    const listApi = mode === 'product' ? mocks.listProductGroups : mocks.listInventory
    const otherListApi = mode === 'product' ? mocks.listInventory : mocks.listProductGroups
    const expectedFilters = mode === 'product'
      ? { ...sharedFilters, specifications: ['标准'] }
      : { ...sharedFilters, specification: '标准' }
    expect(listApi).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ ...expectedFilters, page: 1 }))
    expect(otherListApi).not.toHaveBeenCalled()
    expect(mocks.inventoryStats).toHaveBeenCalledExactlyOnceWith(expect.objectContaining(expectedFilters))
    const statsParams = mocks.inventoryStats.mock.calls[0][0]
    if (mode === 'product') expect(statsParams.view).toBe('product')
    else expect(statsParams).not.toHaveProperty('view')
    expect(workbench.find('.inventory-filter-check input').element.checked).toBe(true)
    expect(workbench.find('[aria-label="已选筛选条件"]').text()).toContain('库存：仅低库存')
    expectSummary(wrapper, mode === 'product' ? lowProductSummary : lowOrderSummary)

    // Switching back must not leak low-stock filters or stats into the other view.
    await wrapper.findAll('[role="tab"]')[mode === 'product' ? 0 : 1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.inventory-filter-check input').element.checked).toBe(false)
    expectSummary(wrapper, mode === 'product' ? orderSummary : productSummary)
    expect(mocks.showToast).not.toHaveBeenCalled()
  })
})
