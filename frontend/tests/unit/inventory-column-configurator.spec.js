import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import InventoryColumnConfigurator from '@/components/inventory/InventoryColumnConfigurator.vue'

const columns = [
  { key: 'product_code', label: '产品编码', required: true },
  { key: 'product_name', label: '产品名称' },
  { key: 'actions', label: '操作', required: true },
]

describe('inventory column configurator', () => {
  it('keeps required columns visible and emits optional changes', async () => {
    const wrapper = mount(InventoryColumnConfigurator, {
      props: { columns, visibleKeys: ['product_code', 'product_name', 'actions'] },
    })
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    expect(checkboxes[0].attributes('disabled')).toBeDefined()
    await checkboxes[1].setValue(false)
    expect(wrapper.emitted('update')).toEqual([[['product_code', 'actions']]])
  })

  it('emits reset without mutating the caller state', async () => {
    const wrapper = mount(InventoryColumnConfigurator, {
      props: { columns, visibleKeys: ['product_code', 'actions'] },
    })
    await wrapper.get('.inventory-column-reset').trigger('click')
    expect(wrapper.emitted('reset')).toHaveLength(1)
    expect(wrapper.props('visibleKeys')).toEqual(['product_code', 'actions'])
  })
})
