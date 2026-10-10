import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ProductInventoryTable from '@/components/inventory/ProductInventoryTable.vue'

describe('product inventory frozen columns', () => {
  it('keeps product code, name, and specification as distinct pinned columns', () => {
    const wrapper = mount(ProductInventoryTable, {
      props: {
        groups: [{
          product_id: 1,
          product_code: 'SB-121',
          product_name: '静音机头',
          specification: '加强型',
          quantity: 12,
          available_quantity: 10,
          product_alert_level: 'normal',
        }],
        filters: { keyword: '', quality_status: '', low_stock: false },
        total: 1,
        page: 1,
        limit: 200,
      },
    })

    const scrollRegion = wrapper.get('[role="region"]')
    expect(scrollRegion.attributes('aria-label')).toContain('横向和纵向滚动')
    expect(scrollRegion.attributes('tabindex')).toBe('0')
    expect(wrapper.get('table').attributes('aria-label')).toBe('按产品编码汇总的库存')

    const headers = wrapper.findAll('thead th')
    expect(headers.slice(0, 3).map(header => header.text())).toEqual(['产品编码', '产品名称', '规格'])
    expect(headers.slice(0, 3).every(header => header.classes().includes('inventory-frozen-cell'))).toBe(true)

    const cells = wrapper.findAll('tbody tr').at(0).findAll('td')
    expect(cells.slice(0, 3).map(cell => cell.text())).toEqual(['SB-121', '静音机头', '加强型'])
    expect(cells.slice(0, 3).every(cell => cell.classes().includes('inventory-frozen-cell'))).toBe(true)
    expect(cells.at(0).find('code').classes()).toContain('inventory-product-code')
    expect(headers.at(-1).classes()).toContain('inventory-mobile-actions')
    expect(cells.at(-1).classes()).toContain('inventory-mobile-actions')
  })
})
