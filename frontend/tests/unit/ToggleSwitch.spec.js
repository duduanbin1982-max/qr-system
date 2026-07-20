import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ToggleSwitch from '@/components/common/ToggleSwitch.vue'


describe('ToggleSwitch', () => {
  it('emits the opposite numeric value when toggled', async () => {
    const wrapper = mount(ToggleSwitch, {
      props: { modelValue: 0, label: '启用强拦截' },
    })

    await wrapper.find('label > span:last-child').trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([[1]])
  })
})
