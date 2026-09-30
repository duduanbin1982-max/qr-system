import { computed, reactive, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import InventoryViewTabs from '@/components/inventory/InventoryViewTabs.vue'

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
})
