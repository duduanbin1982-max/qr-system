import { computed, reactive, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import InventoryViewTabs from '@/components/inventory/InventoryViewTabs.vue'

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      inventory: {
        inventoryCapabilities: vi.fn().mockResolvedValue({ product_query_enabled: true }),
        listProductGroups: vi.fn().mockResolvedValue({ items: [], total: 101, page: 1, limit: 200 }),
        inventoryFilterOptions: vi.fn().mockResolvedValue({ specifications: [{ value: '标准', inventory_count: 2 }], quality_statuses: [], locations: [] }),
        inventoryStats: vi.fn().mockResolvedValue({ total_items: 1, total_quantity: 7, total_value: 0, low_stock: 0, today_in: 0, today_out: 0 }),
      },
    },
  },
}))

import { useInventoryProductGroups } from '@/composables/inventory/useInventoryProductGroups.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

describe('inventory product view state binding', () => {
  it('unwraps nested refs at the view boundary so tab state is rendered as values', async () => {
    const rawState = {
      viewMode: ref('order'),
      enabled: computed(() => true),
    }
    const state = reactive(rawState)
    const wrapper = mount({
      components: { InventoryViewTabs },
      setup() {
        return { state }
      },
      template: '<InventoryViewTabs v-model="state.viewMode" :product-enabled="state.enabled" />',
    })

    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toContain('按订单')
    expect(wrapper.findAll('button')[1].attributes('disabled')).toBeUndefined()

    await wrapper.findAll('button')[1].trigger('click')
    expect(state.viewMode).toBe('product')
    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toContain('按产品编码')
  })

  it('requests the full catalogue page by default', async () => {
    localStorage.setItem('inventory-workbench:v1:view', 'product')
    const { api } = await import('@/lib/api.js')
    const wrapper = mount({
      setup() {
        return useInventoryProductGroups()
      },
      template: '<div />',
    })

    await new Promise(resolve => setTimeout(resolve, 0))
    expect(api.domains.inventory.listProductGroups).toHaveBeenCalledWith(expect.objectContaining({ limit: 200, page: 1 }))
    wrapper.unmount()
    localStorage.removeItem('inventory-workbench:v1:view')
  })

  it('loads filter options and keeps product summary aligned with selected specifications', async () => {
    localStorage.setItem('inventory-workbench:v1:view', 'product')
    const { api } = await import('@/lib/api.js')
    const wrapper = mount({
      setup() {
        return useInventoryProductGroups()
      },
      template: '<div />',
    })

    await new Promise(resolve => setTimeout(resolve, 0))
    const calls = api.domains.inventory.listProductGroups.mock.calls
    expect(api.domains.inventory.inventoryFilterOptions).toHaveBeenCalledWith({ view: 'product' })
    expect(api.domains.inventory.inventoryStats).toHaveBeenCalledWith(expect.objectContaining({ view: 'product' }))
    expect(calls.some(([params]) => Array.isArray(params.specifications))).toBe(true)
    wrapper.unmount()
    localStorage.removeItem('inventory-workbench:v1:view')
    localStorage.removeItem('inventory-workbench:v1:filters')
  })

  it('rejects a stale product response and commits list, total, and summary as one snapshot', async () => {
    localStorage.setItem('inventory-workbench:v1:view', 'product')
    const { api } = await import('@/lib/api.js')
    let product
    const wrapper = mount({
      setup() {
        product = useInventoryProductGroups()
        return {}
      },
      template: '<div />',
    })
    await flushPromises()
    const oldList = deferred()
    const oldSummary = deferred()
    const newList = deferred()
    const newSummary = deferred()
    api.domains.inventory.listProductGroups.mockImplementation(params => params.keyword === '新产品' ? newList.promise : oldList.promise)
    api.domains.inventory.inventoryStats.mockImplementation(params => params.keyword === '新产品' ? newSummary.promise : oldSummary.promise)

    product.actions.setFilter({ key: 'keyword', value: '旧产品' })
    const oldRequest = product.actions.searchGroups()
    product.actions.setFilter({ key: 'keyword', value: '新产品' })
    const newRequest = product.actions.searchGroups()

    newList.resolve({ items: [{ product_id: 22, product_code: 'NEW-22' }], total: 1 })
    await Promise.resolve()
    expect(product.state.groups.value).toEqual([])
    expect(product.state.loading.value).toBe(true)

    newSummary.resolve({ total_items: 1, total_quantity: 22, total_value: 220 })
    await newRequest
    expect(product.state.groups.value).toEqual([{ product_id: 22, product_code: 'NEW-22' }])
    expect(product.state.total.value).toBe(1)
    expect(product.state.summary.value).toEqual({ total_items: 1, total_quantity: 22, total_value: 220, low_stock: 0, today_in: 0, today_out: 0 })

    oldList.resolve({ items: [{ product_id: 11, product_code: 'OLD-11' }], total: 99 })
    oldSummary.resolve({ total_items: 99, total_quantity: 999, total_value: 9990 })
    await oldRequest
    expect(product.state.groups.value).toEqual([{ product_id: 22, product_code: 'NEW-22' }])
    expect(product.state.total.value).toBe(1)
    expect(product.state.summary.value).toEqual({ total_items: 1, total_quantity: 22, total_value: 220, low_stock: 0, today_in: 0, today_out: 0 })
    expect(product.state.loading.value).toBe(false)
    wrapper.unmount()
    localStorage.removeItem('inventory-workbench:v1:view')
    localStorage.removeItem('inventory-workbench:v1:filters')
  })
})
