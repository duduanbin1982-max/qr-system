import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ProductInventoryTable from '@/components/inventory/ProductInventoryTable.vue'

function groups(count) {
  return Array.from({ length: count }, (_, index) => ({
    product_id: index + 1,
    product_code: `P-${index + 1}`,
    product_name: `产品-${index + 1}`,
    quantity: 1,
    reserved_quantity: 0,
    frozen_quantity: 0,
    available_quantity: 1,
    order_count: 1,
    lot_count: 1,
    location_count: 1,
    product_alert_level: 'normal',
  }))
}

describe('product inventory catalogue pagination', () => {
  it('only shows filtered export to users with inventory export permission', () => {
    const hidden = mount(ProductInventoryTable, {
      props: {
        groups: groups(1),
        filters: { keyword: '', quality_status: '', low_stock: false },
        total: 1,
        canExport: false,
      },
    })
    expect(hidden.text()).not.toContain('导出当前筛选')

    const visible = mount(ProductInventoryTable, {
      props: {
        groups: groups(1),
        filters: { keyword: '', quality_status: '', low_stock: false },
        total: 1,
        canExport: true,
      },
    })
    expect(visible.text()).toContain('导出当前筛选')
  })

  it('shows the complete catalogue when the API returns up to 200 groups', () => {
    const wrapper = mount(ProductInventoryTable, {
      props: {
        groups: groups(101),
        filters: { keyword: '', quality_status: '', low_stock: false },
        total: 101,
        page: 1,
        limit: 200,
      },
    })

    expect(wrapper.findAll('tbody tr')).toHaveLength(101)
    expect(wrapper.text()).toContain('共 101 个产品，当前显示 1–101')
    const paginationButtons = wrapper.findAll('.product-pagination button')
    expect(paginationButtons[1].attributes('disabled')).toBeDefined()
  })

  it('emits page changes and renders the visible range for larger catalogues', async () => {
    const wrapper = mount(ProductInventoryTable, {
      props: {
        groups: groups(50),
        filters: { keyword: '', quality_status: '', low_stock: false },
        total: 250,
        page: 2,
        limit: 200,
      },
    })

    expect(wrapper.text()).toContain('共 250 个产品，当前显示 201–250')
    const buttons = wrapper.findAll('.product-pagination button')
    await buttons[0].trigger('click')
    expect(wrapper.emitted('change-page')).toEqual([[1]])
    expect(buttons[1].attributes('disabled')).toBeDefined()
  })
})
