import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import NodeEditorPanel from '@/components/production-nodes/NodeEditorPanel.vue'

function formFixture(overrides = {}) {
  return reactive({
    id: 11,
    process_id: 7,
    node_code: 'WELD-01',
    node_name: '焊接-01',
    capacity_mode: 'exclusive',
    calendar_id: 1,
    status: 'active',
    reason: '',
    idempotency_key: 'node-11-update',
    ...overrides,
  })
}

function mountEditor(options = {}) {
  return mount(NodeEditorPanel, {
    props: {
      form: options.form || formFixture(),
      processOptions: [{ id: 7, name: '焊接' }],
      calendars: [{ id: 1, calendar_name: '九小时工作制' }],
      canManage: true,
      saving: false,
      onReset: vi.fn(),
      onSave: vi.fn(),
      ...options.props,
    },
  })
}

describe('NodeEditorPanel', () => {
  it('locks the process for existing nodes and emits dirty changes', async () => {
    const wrapper = mountEditor()

    expect(wrapper.get('[data-test="node-process"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="node-name"]').setValue('焊接主节点')

    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])
  })

  it('binds every editable node field directly to the supplied form', async () => {
    const form = formFixture({ id: null, process_id: '' })
    const wrapper = mountEditor({ form })

    await wrapper.get('[data-test="node-process"]').setValue('7')
    await wrapper.get('[data-test="node-code"]').setValue('WELD-02')
    await wrapper.get('[data-test="node-capacity-mode"]').setValue('batch')
    await wrapper.get('[data-test="node-calendar"]').setValue('1')
    await wrapper.get('[data-test="node-status"]').setValue('maintenance')
    await wrapper.get('[data-test="node-reason"]').setValue('调整节点')
    await wrapper.get('[data-test="node-idempotency-key"]').setValue('node-new')

    expect(form).toMatchObject({
      process_id: 7,
      node_code: 'WELD-02',
      capacity_mode: 'batch',
      calendar_id: 1,
      status: 'maintenance',
      reason: '调整节点',
      idempotency_key: 'node-new',
    })
  })

  it('preserves dirty input after a failed save and emits saved after success', async () => {
    const form = formFixture()
    const onSave = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce({ id: 11 })
    const wrapper = mountEditor({ form, props: { onSave } })

    await wrapper.get('[data-test="node-name"]').setValue('焊接主节点')
    await wrapper.get('form').trigger('submit')
    expect(form.node_name).toBe('焊接主节点')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])
    expect(wrapper.emitted('saved')).toBeUndefined()

    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([false])
    expect(wrapper.emitted('saved')).toEqual([[{ id: 11 }]])
  })

  it('shows labelled read-only values without form controls when management is forbidden', () => {
    const wrapper = mountEditor({ props: { canManage: false } })

    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('焊接')
    expect(wrapper.text()).toContain('WELD-01')
    expect(wrapper.text()).toContain('九小时工作制')
    expect(wrapper.text()).toContain('启用')
  })

  it('disables save while saving and delegates reset to the controller', async () => {
    const onReset = vi.fn()
    const wrapper = mountEditor({ props: { saving: true, onReset } })

    expect(wrapper.get('[data-test="node-save"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="node-reset"]').trigger('click')
    expect(onReset).toHaveBeenCalledOnce()
  })
})
