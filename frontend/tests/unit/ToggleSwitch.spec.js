import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ToggleSwitch from '@/components/common/ToggleSwitch.vue'


describe('ToggleSwitch', () => {
  it('emits the opposite numeric value when toggled', async () => {
    const wrapper = mount(ToggleSwitch, {
      props: { modelValue: 0, label: '启用强拦截' },
    })

    await wrapper.find('button[role="switch"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([[1]])
  })

  it('does not emit while disabled', async () => {
    const wrapper = mount(ToggleSwitch, {
      props: { modelValue: 1, label: '启用报工审批', disabled: true },
    })

    await wrapper.find('button[role="switch"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.find('button').attributes('aria-checked')).toBe('true')
  })
})
