import { computed, reactive, ref } from 'vue'
import { mount } from '@vue/test-utils'
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
})
