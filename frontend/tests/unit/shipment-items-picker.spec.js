import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ShipmentItemsPicker from '@/components/shipments/ShipmentItemsPicker.vue'


function buildItem(overrides = {}) {
  return {
    inventory_id: '',
    product_model: '',
    product_name: '',
    quantity: 1,
    unit: '件',
    _search: '',
    _showDrop: false,
    _options: null,
    _loading: false,
    ...overrides,
  }
}

describe('ShipmentItemsPicker server-side search results', () => {
  it('renders server search options including the order number', () => {
    const wrapper = mount(ShipmentItemsPicker, {
      props: {
        items: [buildItem({
          _search: '26070805',
          _showDrop: true,
          _options: [{
            id: 59,
            product_model: '外壳-SB81-JY-360-20-折弯款',
            product_name: '外壳',
            order_no: '26070805',
            quantity: 7,
          }],
        })],
        inventory: [],
      },
    })

    expect(wrapper.find('.shipment-items__dropdown').exists()).toBe(true)
    expect(wrapper.text()).toContain('26070805')
    expect(wrapper.text()).toContain('外壳')
  })

  it('shows a loading hint while the server search is running', () => {
    const wrapper = mount(ShipmentItemsPicker, {
      props: {
        items: [buildItem({ _search: '26070805', _showDrop: true, _loading: true })],
        inventory: [],
      },
    })

    expect(wrapper.text()).toContain('搜索中')
  })

  it('shows the empty hint when the server returns no rows', () => {
    const wrapper = mount(ShipmentItemsPicker, {
      props: {
        items: [buildItem({ _search: 'UNKNOWN', _showDrop: true, _options: [] })],
        inventory: [],
      },
    })

    expect(wrapper.text()).toContain('无匹配产品')
  })
})
