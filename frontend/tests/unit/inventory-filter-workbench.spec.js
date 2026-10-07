import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import InventoryFilterWorkbench from '@/components/inventory/InventoryFilterWorkbench.vue'

describe('inventory filter workbench', () => {
  const baseProps = {
    filters: {
      keyword: '待出库',
      location: '东库',
      quality_status: 'qualified',
      low_stock: true,
      specifications: ['标准', '加厚'],
    },
    filterOptions: {
      locations: [{ value: '东库', inventory_count: 2 }],
      quality_statuses: [{ value: 'qualified', inventory_count: 2 }],
      specifications: [{ value: '标准', inventory_count: 1 }, { value: '加厚', inventory_count: 1 }],
    },
    savedFilters: [{ id: 'preset-1', name: '东库待出库', filters: {} }],
    resultCount: 2,
  }

  it('renders selected chips and emits a single-condition clear event', async () => {
    const wrapper = mount(InventoryFilterWorkbench, { props: baseProps })
    expect(wrapper.find('[aria-label="已选筛选条件"]').exists()).toBe(true)
    expect(wrapper.findAll('.inventory-filter-chip')).toHaveLength(6)

    await wrapper.findAll('.inventory-filter-chip')[1].trigger('click')
    expect(wrapper.emitted('clear-filter')[0][0]).toEqual({ key: 'location', value: '东库' })
  })

  it('emits filter updates and named save/apply actions', async () => {
    const wrapper = mount(InventoryFilterWorkbench, { props: baseProps })
    await wrapper.find('input[placeholder="例如：待出库-东库"]').setValue('重点库存')
    await wrapper.findAll('button').find(button => button.text() === '保存当前条件').trigger('click')
    expect(wrapper.emitted('save-filter')).toEqual([['重点库存']])

    await wrapper.find('.inventory-filter-keyword input').setValue('新的关键字')
    expect(wrapper.emitted('update-filter').at(-1)[0]).toEqual({ key: 'keyword', value: '新的关键字' })

    await wrapper.find('.inventory-saved-select').setValue('preset-1')
    await wrapper.findAll('button').find(button => button.text() === '恢复').trigger('click')
    expect(wrapper.emitted('apply-filter')).toHaveLength(1)
  })
})
