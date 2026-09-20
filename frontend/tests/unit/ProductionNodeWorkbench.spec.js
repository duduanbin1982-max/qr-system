import { mount } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProductionNodeWorkbench from '@/components/production-nodes/ProductionNodeWorkbench.vue'

function managerFixture(overrides = {}) {
  const nodes = ref(overrides.nodes || [
    {
      id: 11,
      process_id: 7,
      process_name: '焊接',
      node_code: 'WELD-01',
      node_name: '焊接-01',
      status: 'active',
      capacity_mode: 'exclusive',
    },
    {
      id: 12,
      process_id: 8,
      process_name: '装配',
      node_code: 'ASSY-01',
      node_name: '装配-01',
      status: 'inactive',
      capacity_mode: 'shared',
    },
  ])

  return {
    state: {
      productionNodes: nodes,
      productionCalendars: ref([]),
      nodesLoading: ref(false),
      nodesError: ref(''),
      nodeForm: ref({}),
      nodeSaving: ref(false),
      overrideForm: ref({}),
      nodeOverrides: ref([]),
      overridesLoading: ref(false),
      overridesError: ref(''),
      overrideSaving: ref(false),
      capabilityForm: ref({ capabilities: [] }),
      capabilitiesLoading: ref(false),
      capabilitiesError: ref(''),
      capabilitySaving: ref(false),
    },
    permissions: {
      canManageNodes: ref(true),
      canManageCapabilities: ref(true),
      canManageCalendars: ref(true),
    },
    actions: {
      loadNodes: vi.fn(),
      resetNodeForm: vi.fn(),
      editNode: vi.fn(),
      saveNode: vi.fn(),
      prepareOverride: vi.fn(),
      loadOverrides: vi.fn(),
      createCalendarOverride: vi.fn(),
      cancelOverride: vi.fn(),
      loadCapabilities: vi.fn(),
      addCapability: vi.fn(),
      removeCapability: vi.fn(),
      saveCapabilities: vi.fn(),
    },
  }
}

function mountWorkbench(options = {}) {
  const trigger = document.createElement('button')
  trigger.textContent = '打开节点管理'
  document.body.appendChild(trigger)
  trigger.focus()

  const manager = options.manager || managerFixture()
  const wrapper = mount(ProductionNodeWorkbench, {
    props: {
      modelValue: true,
      manager,
      processOptions: [],
      ...options.props,
    },
    slots: options.slots,
    attachTo: document.body,
  })

  return { manager, trigger, wrapper }
}

afterEach(() => {
  document.body.innerHTML = ''
  document.body.style.overflow = ''
})

describe('ProductionNodeWorkbench', () => {
  it('teleports a labelled modal workbench to body and does not close on overlay click', async () => {
    const { wrapper } = mountWorkbench()
    const dialog = document.body.querySelector('[role="dialog"]')

    expect(dialog).not.toBeNull()
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.getAttribute('aria-labelledby')).toBe('production-node-workbench-title')
    expect(document.body.style.overflow).toBe('hidden')

    await document.body.querySelector('.node-workbench-overlay').click()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('renders grouped selectable nodes and wires search, status, retry, and create actions', async () => {
    const { manager } = mountWorkbench()

    expect(document.body.querySelector('[data-test="node-item-11"]')).not.toBeNull()
    expect(document.body.querySelector('[data-test="node-item-12"]')).not.toBeNull()

    const search = document.body.querySelector('[data-test="node-search"]')
    search.value = '装配'
    search.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    expect(document.body.querySelector('[data-test="node-item-11"]')).toBeNull()
    expect(document.body.querySelector('[data-test="node-item-12"]')).not.toBeNull()

    const status = document.body.querySelector('[data-test="node-status-filter"]')
    status.value = 'active'
    status.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(document.body.textContent).toContain('没有符合条件的生产节点')

    await document.body.querySelector('[data-test="node-create"]').click()
    expect(manager.actions.resetNodeForm).toHaveBeenCalledOnce()
    expect(manager.actions.editNode).not.toHaveBeenCalled()
  })

  it('selects the initial node and supports node selection from desktop and mobile controls', async () => {
    const { manager } = mountWorkbench()

    await nextTick()
    expect(document.body.querySelector('[data-test="node-item-11"]').getAttribute('aria-current')).toBe('true')

    await document.body.querySelector('[data-test="node-item-12"]').click()
    const editorTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '节点编辑')
    await editorTab.click()
    expect(manager.actions.editNode).toHaveBeenLastCalledWith(expect.objectContaining({ id: 12 }))

    const mobileSelect = document.body.querySelector('[data-test="mobile-node-select"]')
    mobileSelect.value = '11'
    mobileSelect.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    expect(manager.actions.editNode).toHaveBeenLastCalledWith(expect.objectContaining({ id: 11 }))
  })

  it('guards close while dirty and closes only after discard confirmation', async () => {
    const { wrapper } = mountWorkbench({
      slots: {
        default: ({ markDirty }) => h(
          'button',
          { 'data-test': 'make-dirty', onClick: () => markDirty() },
          '修改',
        ),
      },
    })

    await document.body.querySelector('[data-test="make-dirty"]').click()
    await document.body.querySelector('.node-workbench__footer button').click()

    expect(document.body.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()

    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(wrapper.emitted('closed')).toEqual([[]])
  })

  it('traps focus, handles Escape, restores focus, and unlocks body scrolling', async () => {
    document.body.style.overflow = 'auto'
    const { trigger, wrapper } = mountWorkbench()
    await nextTick()

    const dialog = document.body.querySelector('.node-workbench')
    const focusable = [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
    const first = focusable[0]
    const last = focusable.at(-1)

    last.focus()
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(first)

    first.focus()
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(last)

    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])

    await wrapper.setProps({ modelValue: false })
    expect(document.body.style.overflow).toBe('auto')
    expect(document.activeElement).toBe(trigger)
  })

  it('shows loading and error states and retries loading nodes', async () => {
    const manager = managerFixture()
    manager.state.nodesLoading.value = true
    const { wrapper } = mountWorkbench({ manager })

    expect(document.body.textContent).toContain('正在加载生产节点')

    manager.state.nodesLoading.value = false
    manager.state.nodesError.value = '节点加载失败'
    await nextTick()
    expect(document.body.textContent).toContain('节点加载失败')

    await document.body.querySelector('[data-test="node-retry"]').click()
    expect(manager.actions.loadNodes).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})
