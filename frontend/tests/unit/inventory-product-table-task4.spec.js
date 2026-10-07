import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ProductInventoryTable from '@/components/inventory/ProductInventoryTable.vue'

const group = { product_id: 1, product_code: 'P-1', product_name: '产品 1', specification: '标准', available_quantity: 3, product_alert_level: 'normal' }

describe('product inventory task 4 table interactions', () => {
  it('emits sorting and page selection actions', async () => {
    const wrapper = mount(ProductInventoryTable, {
      props: {
        groups: [group],
        filters: { keyword: '', quality_status: '', low_stock: false },
        columns: [
          { key: 'product_code', label: '产品编码', required: true },
          { key: 'product_name', label: '产品名称', required: true },
          { key: 'specification', label: '规格', required: true },
          { key: 'available_quantity', label: '可用' },
          { key: 'actions', label: '操作', required: true },
        ],
        visibleColumns: ['product_code', 'product_name', 'specification', 'available_quantity', 'actions'],
        selectedIds: [],
        selectedCount: 0,
        canExport: true,
        total: 1,
      },
    })
    await wrapper.get('.inventory-sort-button').trigger('click')
    expect(wrapper.emitted('sort')).toEqual([['product_code']])
    await wrapper.get('.inventory-page-select input').setValue(true)
    expect(wrapper.emitted('toggle-select-all')).toHaveLength(1)
  })

  it('shows a confirmed batch export entry only when selected rows exist', () => {
    const wrapper = mount(ProductInventoryTable, {
      props: { groups: [group], filters: {}, selectedIds: [1], selectedCount: 1, canExport: true, total: 1 },
    })
    expect(wrapper.text()).toContain('批量导出')
  })
})
