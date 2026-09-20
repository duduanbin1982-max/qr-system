import { flushPromises, mount } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import NodeListPanel from '@/components/production-nodes/NodeListPanel.vue'
import NodeEditorPanel from '@/components/production-nodes/NodeEditorPanel.vue'
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
      nodeForm: ref({
        id: null,
        process_id: '',
        node_code: '',
        node_name: '',
        capacity_mode: 'exclusive',
        calendar_id: '',
        status: 'active',
        reason: '',
        idempotency_key: 'node-new',
      }),
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

  it('does not expose or run the create workflow without node-management permission', async () => {
    const manager = managerFixture()
    manager.permissions.canManageNodes.value = false
    const { wrapper } = mountWorkbench({ manager })

    expect(document.body.querySelector('[data-test="node-create"]')).toBeNull()

    wrapper.findComponent(NodeListPanel).vm.$emit('create')
    await nextTick()
    expect(manager.actions.resetNodeForm).not.toHaveBeenCalled()
  })

  it('guards the create workflow until dirty changes are explicitly discarded', async () => {
    const manager = managerFixture()
    manager.state.nodeForm.value = { id: 11, node_name: '未保存名称' }
    const { wrapper } = mountWorkbench({
      manager,
      slots: {
        default: ({ markDirty }) => h(
          'button',
          { 'data-test': 'make-dirty', onClick: () => markDirty() },
          '修改',
        ),
      },
    })
    await nextTick()

    await document.body.querySelector('[data-test="make-dirty"]').click()
    await document.body.querySelector('[data-test="node-create"]').click()

    expect(document.body.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(manager.actions.resetNodeForm).not.toHaveBeenCalled()
    expect(manager.state.nodeForm.value).toEqual({ id: 11, node_name: '未保存名称' })
    expect(document.body.querySelector('[data-test="node-item-11"]').getAttribute('aria-current')).toBe('true')
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('节点列表')

    const continueEditing = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '继续编辑')
    await continueEditing.click()
    await nextTick()

    expect(document.body.querySelector('[role="alertdialog"]')).toBeNull()
    expect(manager.actions.resetNodeForm).not.toHaveBeenCalled()
    expect(manager.state.nodeForm.value).toEqual({ id: 11, node_name: '未保存名称' })
    expect(document.body.querySelector('[data-test="node-item-11"]').getAttribute('aria-current')).toBe('true')
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('节点列表')

    await document.body.querySelector('[data-test="node-create"]').click()
    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await nextTick()

    expect(manager.actions.resetNodeForm).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[data-test="node-item-11"]').getAttribute('aria-current')).toBeNull()
    expect(document.body.querySelector('[data-test="mobile-node-select"]').value).toBe('')
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('节点编辑')

    await document.body.querySelector('.node-workbench__footer button').click()
    expect(document.body.querySelector('[role="alertdialog"]')).toBeNull()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
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

  it('renders the editor tab from manager state and reloads and reselects after save', async () => {
    const manager = managerFixture()
    manager.actions.saveNode.mockResolvedValue({ id: 12 })
    const { wrapper } = mountWorkbench({ manager, props: { processOptions: [{ id: 7, name: '焊接' }] } })
    const editorTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '节点编辑')

    await editorTab.click()
    await nextTick()

    expect(wrapper.findComponent(NodeEditorPanel).exists()).toBe(true)
    expect(manager.actions.editNode).toHaveBeenLastCalledWith(expect.objectContaining({ id: 11 }))

    wrapper.findComponent(NodeEditorPanel).vm.$emit('saved', { id: 12 })
    await flushPromises()

    expect(manager.actions.loadNodes).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[data-test="node-item-12"]').getAttribute('aria-current')).toBe('true')
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

  it('wraps Shift+Tab from the initially focused title back into the dialog', async () => {
    mountWorkbench()
    await nextTick()

    const dialog = document.body.querySelector('.node-workbench')
    const title = document.body.querySelector('#production-node-workbench-title')
    const focusable = [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]

    expect(document.activeElement).toBe(title)
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(focusable.at(-1))
  })

  it('moves focus into the discard alert, traps it there, and restores it when editing continues', async () => {
    mountWorkbench({
      slots: {
        default: ({ markDirty }) => h(
          'button',
          { 'data-test': 'make-dirty', onClick: () => markDirty() },
          '修改',
        ),
      },
    })

    await document.body.querySelector('[data-test="make-dirty"]').click()
    const closeButton = document.body.querySelector('.node-workbench__footer button')
    closeButton.focus()
    await closeButton.click()
    await nextTick()

    const dialog = document.body.querySelector('.node-workbench')
    const alert = document.body.querySelector('.node-discard-dialog')
    const alertButtons = [...alert.querySelectorAll('button')]
    expect(document.activeElement).toBe(alertButtons[0])

    alertButtons[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(alertButtons.at(-1))

    alertButtons.at(-1).dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(alertButtons[0])

    document.body.querySelector('#production-node-workbench-title').focus()
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(alertButtons[0])

    await alertButtons[0].click()
    await nextTick()
    expect(document.body.querySelector('.node-discard-dialog')).toBeNull()
    expect(document.activeElement).toBe(closeButton)
  })

  it('does not alter an existing body scroll lock when mounted closed', async () => {
    document.body.style.overflow = 'hidden'
    const { wrapper } = mountWorkbench({ props: { modelValue: false } })
    await nextTick()

    expect(document.body.style.overflow).toBe('hidden')
    wrapper.unmount()
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('releases scroll and restores focus once, then leaves later modal ownership untouched on unmount', async () => {
    document.body.style.overflow = 'auto'
    const { trigger, wrapper } = mountWorkbench()
    const focusSpy = vi.spyOn(trigger, 'focus')
    await nextTick()

    await wrapper.setProps({ modelValue: false })
    expect(document.body.style.overflow).toBe('auto')
    expect(focusSpy).toHaveBeenCalledOnce()

    const laterModalControl = document.createElement('button')
    document.body.appendChild(laterModalControl)
    laterModalControl.focus()
    document.body.style.overflow = 'hidden'

    wrapper.unmount()
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.activeElement).toBe(laterModalControl)
    expect(focusSpy).toHaveBeenCalledOnce()
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
