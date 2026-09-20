import { flushPromises, mount } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import NodeListPanel from '@/components/production-nodes/NodeListPanel.vue'
import NodeCapabilityPanel from '@/components/production-nodes/NodeCapabilityPanel.vue'
import NodeCalendarPanel from '@/components/production-nodes/NodeCalendarPanel.vue'
import NodeEditorPanel from '@/components/production-nodes/NodeEditorPanel.vue'
import ProductionNodeWorkbench from '@/components/production-nodes/ProductionNodeWorkbench.vue'
import productionNodeWorkbenchSource from '@/components/production-nodes/ProductionNodeWorkbench.vue?raw'
import { useProductionNodes } from '@/composables/gantt/useProductionNodes.js'

const productionMocks = vi.hoisted(() => ({
  listProductionNodes: vi.fn(),
  listScheduleCalendars: vi.fn(),
  createProductionNodeOverride: vi.fn(),
  listProductionNodeOverrides: vi.fn(),
  listProductionNodeCapabilities: vi.fn(),
  replaceProductionNodeCapabilities: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      production: {
        listProductionNodes: productionMocks.listProductionNodes,
        listScheduleCalendars: productionMocks.listScheduleCalendars,
        createProductionNodeOverride: productionMocks.createProductionNodeOverride,
        listProductionNodeOverrides: productionMocks.listProductionNodeOverrides,
        listProductionNodeCapabilities: productionMocks.listProductionNodeCapabilities,
        replaceProductionNodeCapabilities: productionMocks.replaceProductionNodeCapabilities,
      },
    },
  },
}))

vi.mock('@/lib/store.js', () => ({ showToast: productionMocks.showToast }))

function deferredCommand() {
  let resolve
  const promise = new Promise(resolvePromise => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

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
      capacity_mode: 'batch',
    },
  ])

  const currentNodeId = ref(null)

  return {
    state: {
      productionNodes: nodes,
      productionCalendars: ref([]),
      currentNodeId,
      nodeSummary: ref({
        production_node_id: 11,
        capability_count: 2,
        future_override_count: 1,
      }),
      nodeSummaryLoading: ref(false),
      nodeSummaryError: ref(''),
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
      canViewNodes: ref(true),
      canManageNodes: ref(true),
      canManageCapabilities: ref(true),
      canManageCalendars: ref(true),
    },
    actions: {
      loadNodes: vi.fn(),
      selectNodeContext: vi.fn(node => {
        currentNodeId.value = node?.id ?? null
      }),
      loadNodeSummary: vi.fn(),
      rollbackPanel: vi.fn(),
      resetWorkbenchSession: vi.fn(() => {
        currentNodeId.value = null
      }),
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
  mountedWrappers.push(wrapper)

  return { manager, trigger, wrapper }
}

const mountedWrappers = []

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) {
    if (wrapper.exists()) wrapper.unmount()
  }
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

  it('renders the selected-node summary and an intentional empty state', async () => {
    const manager = managerFixture()
    manager.state.productionNodes.value[0].capacity_minutes = 540
    mountWorkbench({ manager })
    await nextTick()

    const summary = document.body.querySelector('[data-test="node-summary"]')
    expect(summary).not.toBeNull()
    expect(summary.textContent).toContain('WELD-01')
    expect(summary.textContent).toContain('焊接-01')
    expect(summary.textContent).toContain('540 分钟')
    expect(summary.textContent).toContain('2 条')
    expect(summary.textContent).toContain('1 条')
    expect(manager.actions.loadNodeSummary).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }))

    const emptyManager = managerFixture({ nodes: [] })
    mountWorkbench({ manager: emptyManager })
    await nextTick()
    expect(document.body.textContent).toContain('请选择生产节点查看摘要')
  })

  it('uses standard keyboard tab semantics and ARIA panel relationships', async () => {
    mountWorkbench()
    await nextTick()
    const tabs = [...document.body.querySelectorAll('[role="tab"]')]

    expect(tabs.map(tab => tab.getAttribute('tabindex'))).toEqual(['0', '-1', '-1', '-1'])
    for (const tab of tabs) {
      const panelId = tab.getAttribute('aria-controls')
      expect(tab.id).toBeTruthy()
      expect(panelId).toBeTruthy()
      const panel = document.body.querySelector(`#${panelId}`)
      expect(panel?.getAttribute('role')).toBe('tabpanel')
      expect(panel?.getAttribute('aria-labelledby')).toBe(tab.id)
    }

    tabs[0].focus()
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await nextTick()
    expect(tabs[1].getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[1])

    tabs[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }))
    await nextTick()
    expect(tabs.at(-1).getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs.at(-1))

    tabs.at(-1).dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }))
    await nextTick()
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[0])

    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
    await nextTick()
    expect(tabs.at(-1).getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs.at(-1))
  })

  it('focuses the newly active tab after a dirty keyboard transition is discarded', async () => {
    mountWorkbench({
      slots: {
        default: ({ markDirty }) => h(
          'button',
          { 'data-test': 'make-dirty', onClick: () => markDirty() },
          '修改',
        ),
      },
    })
    await nextTick()
    const tabs = [...document.body.querySelectorAll('[role="tab"]')]
    await document.body.querySelector('[data-test="make-dirty"]').click()
    tabs[0].focus()
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await nextTick()

    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(tabs[1].getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[1])
  })

  it('keeps roving tab focus on the active tab when a mouse transition is cancelled', async () => {
    mountWorkbench({
      slots: {
        default: ({ markDirty }) => h(
          'button',
          { 'data-test': 'make-dirty', onClick: () => markDirty() },
          '修改',
        ),
      },
    })
    await nextTick()
    const tabs = [...document.body.querySelectorAll('[role="tab"]')]
    await document.body.querySelector('[data-test="make-dirty"]').click()
    await tabs[1].click()
    const continueEditing = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '继续编辑')
    await continueEditing.click()
    await nextTick()

    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[0])
  })

  it('restores destination tab focus before an async discarded transition settles', async () => {
    const pendingLoad = deferredCommand()
    const manager = managerFixture()
    manager.actions.loadCapabilities.mockReturnValueOnce(pendingLoad.promise)
    mountWorkbench({
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
    const tabs = [...document.body.querySelectorAll('[role="tab"]')]
    const makeDirty = document.body.querySelector('[data-test="make-dirty"]')
    await makeDirty.click()
    tabs[0].focus()
    await tabs[2].click()
    await nextTick()

    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    discard?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()

    expect(tabs[2].getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[2])

    pendingLoad.resolve()
    await flushPromises()
  })

  it('keeps the small-screen tab strip horizontally scrollable', () => {
    expect(productionNodeWorkbenchSource).toMatch(/\.node-workbench__tabs\s*\{[^}]*overflow-x:\s*auto/s)
    expect(productionNodeWorkbenchSource).toMatch(/\.node-workbench__tabs button\s*\{[^}]*flex:\s*0 0 auto/s)
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

  it('invalidates detail contexts and hides detail writes when creating a node clears selection', async () => {
    const manager = managerFixture()
    const { wrapper } = mountWorkbench({ manager })
    await nextTick()

    await document.body.querySelector('[data-test="node-create"]').click()
    await nextTick()

    expect(manager.actions.selectNodeContext).toHaveBeenLastCalledWith(null)
    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await calendarTab.click()
    await nextTick()
    expect(wrapper.findComponent(NodeCalendarPanel).find('[data-test="override-save"]').exists()).toBe(false)

    const capabilityTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '能力限制')
    await capabilityTab.click()
    await nextTick()
    expect(wrapper.findComponent(NodeCapabilityPanel).find('[data-test="capability-save"]').exists()).toBe(false)
    expect(wrapper.findComponent(NodeCapabilityPanel).find('[data-test="capability-add"]').exists()).toBe(false)
  })

  it('does not let an inactive panel refresh clear the active panel dirty guard', async () => {
    const manager = managerFixture()
    manager.state.overrideForm.value = {
      production_node_id: 11,
      start_at: '',
      end_at: '',
      override_type: 'maintenance',
      reason: '',
      idempotency_key: 'calendar-11',
    }
    const { wrapper } = mountWorkbench({ manager })
    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await calendarTab.click()
    await flushPromises()
    await wrapper.findComponent(NodeCalendarPanel)
      .get('[data-test="override-reason"]').setValue('未保存检修')

    manager.state.capabilityForm.value = {
      production_node_id: 11,
      node_label: 'WELD-01 · 焊接-01',
      capabilities: [{ product_family: '异步刷新', status: 'active' }],
      reason: '',
      idempotency_key: 'capability-11-refresh',
    }
    await nextTick()
    await document.body.querySelector('.node-workbench__footer button').click()

    expect(document.body.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
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

  it('treats Escape inside the discard alert as continue editing without replacing the pending action', async () => {
    const manager = managerFixture()
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
    const alert = document.body.querySelector('[role="alertdialog"]')

    alert.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    }))
    await nextTick()

    expect(document.body.querySelector('[role="alertdialog"]')).toBeNull()
    expect(manager.actions.resetNodeForm).not.toHaveBeenCalled()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    await document.body.querySelector('[data-test="node-create"]').click()
    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(manager.actions.resetNodeForm).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('节点编辑')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('rolls back editor data before a confirmed dirty tab change', async () => {
    const manager = managerFixture()
    manager.actions.editNode.mockImplementation(node => {
      manager.state.nodeForm.value = {
        ...node,
        reason: '',
        idempotency_key: `node-${node.id}`,
      }
    })
    manager.actions.rollbackPanel.mockImplementation(tab => {
      if (tab === 'editor') manager.actions.editNode(manager.state.productionNodes.value[0])
    })
    const { wrapper } = mountWorkbench({ manager })
    await nextTick()
    const editorTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '节点编辑')
    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await editorTab.click()
    await nextTick()
    await wrapper.findComponent(NodeEditorPanel).get('[data-test="node-name"]').setValue('未保存名称')

    await calendarTab.click()
    await nextTick()
    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(manager.actions.rollbackPanel).toHaveBeenCalledWith(
      'editor',
      expect.objectContaining({ id: 11 }),
    )
    expect(manager.state.nodeForm.value.node_name).toBe('焊接-01')
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('工作日历')
  })

  it('rolls back calendar data before a confirmed dirty node change', async () => {
    const manager = managerFixture()
    manager.state.overrideForm.value = {
      production_node_id: 11,
      start_at: '',
      end_at: '',
      override_type: 'maintenance',
      reason: '',
      idempotency_key: 'calendar-11',
    }
    manager.actions.prepareOverride.mockImplementation(node => {
      manager.state.overrideForm.value = {
        production_node_id: node.id,
        start_at: '',
        end_at: '',
        override_type: 'maintenance',
        reason: '',
        idempotency_key: `calendar-${node.id}`,
      }
    })
    manager.actions.rollbackPanel.mockImplementation(tab => {
      if (tab === 'calendar') manager.actions.prepareOverride(manager.state.productionNodes.value[0])
    })
    const { wrapper } = mountWorkbench({ manager })
    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await calendarTab.click()
    await flushPromises()
    await wrapper.findComponent(NodeCalendarPanel).get('[data-test="override-reason"]').setValue('未保存检修')

    await document.body.querySelector('[data-test="node-item-12"]').click()
    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(manager.actions.rollbackPanel).toHaveBeenCalledWith(
      'calendar',
      expect.objectContaining({ id: 11 }),
    )
    expect(manager.state.overrideForm.value.production_node_id).toBe(12)
    expect(manager.state.overrideForm.value.reason).toBe('')
    expect(manager.actions.selectNodeContext).toHaveBeenLastCalledWith(expect.objectContaining({ id: 12 }))
  })

  it('rolls back capability data when Escape closes a dirty session', async () => {
    const manager = managerFixture()
    manager.state.capabilityForm.value = {
      production_node_id: 11,
      node_label: 'WELD-01 · 焊接-01',
      capabilities: [{ product_family: 'BASELINE', status: 'active' }],
      reason: '',
      idempotency_key: 'capability-11',
    }
    manager.actions.rollbackPanel.mockImplementation(tab => {
      if (tab === 'capabilities') manager.state.capabilityForm.value.reason = ''
    })
    const { wrapper } = mountWorkbench({ manager })
    const capabilityTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '能力限制')
    await capabilityTab.click()
    await flushPromises()
    await wrapper.findComponent(NodeCapabilityPanel).get('[data-test="capability-reason"]').setValue('未保存能力')

    document.body.querySelector('.node-workbench').dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    }))
    await nextTick()
    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(manager.actions.rollbackPanel).toHaveBeenCalledWith(
      'capabilities',
      expect.objectContaining({ id: 11 }),
    )
    expect(manager.state.capabilityForm.value.reason).toBe('')
    expect(manager.actions.resetWorkbenchSession).toHaveBeenCalledOnce()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('starts a fresh session after close and does not revive discarded editor input', async () => {
    const manager = managerFixture()
    const baselineNode = manager.state.productionNodes.value[0]
    manager.actions.editNode.mockImplementation(node => {
      manager.state.nodeForm.value = {
        ...node,
        reason: '',
        idempotency_key: `node-${node.id}`,
      }
    })
    manager.actions.rollbackPanel.mockImplementation(tab => {
      if (tab === 'editor') manager.actions.editNode(baselineNode)
    })
    manager.actions.resetWorkbenchSession.mockImplementation(() => {
      manager.state.currentNodeId.value = null
      manager.actions.editNode(baselineNode)
    })
    const { wrapper } = mountWorkbench({ manager })
    const editorTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '节点编辑')
    await editorTab.click()
    await nextTick()
    await wrapper.findComponent(NodeEditorPanel).get('[data-test="node-name"]').setValue('应被放弃的名称')
    await document.body.querySelector('.node-workbench__footer button').click()
    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()
    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(manager.actions.resetWorkbenchSession).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('节点列表')
    expect(manager.state.nodeForm.value.node_name).toBe('焊接-01')

    const reopenedEditorTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '节点编辑')
    await reopenedEditorTab.click()
    await nextTick()
    expect(wrapper.findComponent(NodeEditorPanel).get('[data-test="node-name"]').element.value).toBe('焊接-01')
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

  it('loads and displays capability summaries without edit controls for read-only users', async () => {
    const manager = managerFixture()
    manager.permissions.canManageCapabilities.value = false
    manager.state.capabilityForm.value = {
      production_node_id: 11,
      node_label: 'WELD-01 · 焊接-01',
      capabilities: [{
        product_id: 101,
        product_family: 'READ-ONLY',
        material_code: 'MAT-01',
        specification: '20mm',
        route_version_id: 201,
        process_version_id: 301,
        max_batch_quantity: null,
        batch_minutes: null,
        changeover_minutes: 0,
        allow_mixed_orders: false,
        status: 'active',
      }],
      reason: '',
      idempotency_key: 'capability-11',
    }
    const { wrapper } = mountWorkbench({ manager })
    const capabilityTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '能力限制')

    await capabilityTab.click()
    await flushPromises()

    expect(manager.actions.loadCapabilities).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }))
    const panel = wrapper.findComponent(NodeCapabilityPanel)
    expect(panel.get('[data-test="capability-row"]').text()).toContain('READ-ONLY')
    expect(panel.find('input').exists()).toBe(false)
    expect(panel.find('[data-test="capability-save"]').exists()).toBe(false)
  })

  it('does not show node A capability rows when node B capability loading fails', async () => {
    productionMocks.listProductionNodes.mockReset().mockResolvedValue({
      nodes: [
        { id: 11, process_id: 7, process_name: '焊接', node_code: 'A', node_name: '节点 A', status: 'active', capacity_mode: 'exclusive' },
        { id: 12, process_id: 8, process_name: '装配', node_code: 'B', node_name: '节点 B', status: 'active', capacity_mode: 'exclusive' },
      ],
    })
    productionMocks.listScheduleCalendars.mockReset().mockResolvedValue({ calendars: [] })
    productionMocks.listProductionNodeCapabilities
      .mockReset()
      .mockResolvedValueOnce({ capabilities: [] })
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A-ONLY' }] })
      .mockRejectedValueOnce(new Error('B 能力读取失败'))
    productionMocks.listProductionNodeOverrides.mockReset().mockResolvedValue({ overrides: [] })
    const managerState = useProductionNodes({
      canManageNodes: ref(true),
      canManageCapabilities: ref(true),
      canManageCalendars: ref(true),
    })
    await managerState.loadNodes()
    const { wrapper } = mountWorkbench({ manager: managerState.nodeManager })
    const capabilityTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '能力限制')
    await capabilityTab.click()
    await flushPromises()
    expect(wrapper.findComponent(NodeCapabilityPanel)
      .get('[data-test="capability-product-family"]').element.value).toBe('A-ONLY')

    await document.body.querySelector('[data-test="node-item-12"]').click()
    await flushPromises()

    const panel = wrapper.findComponent(NodeCapabilityPanel)
    expect(panel.text()).toContain('B 能力读取失败')
    expect(panel.text()).toContain('B · 节点 B')
    expect(panel.text()).not.toContain('A-ONLY')
    expect(panel.findAll('[data-test="capability-row"]')).toHaveLength(0)
  })

  it('renders the refreshed override list after the manager save action reloads the selected node', async () => {
    const manager = managerFixture()
    manager.state.productionNodes.value = manager.state.productionNodes.value.map(node => ({
      ...node,
      calendar_id: 3,
    }))
    manager.state.productionCalendars.value = [{ id: 3, calendar_name: '生产九小时日历', daily_minutes: 540 }]
    manager.state.overrideForm.value = {
      production_node_id: 11,
      start_at: '2026-09-21T08:00',
      end_at: '2026-09-21T12:00',
      override_type: 'maintenance',
      reason: '新建检修',
      idempotency_key: 'calendar-11',
    }
    manager.actions.loadOverrides.mockImplementation(async node => {
      if (manager.actions.createCalendarOverride.mock.calls.length) {
        manager.state.nodeOverrides.value = [{
          id: 91,
          production_node_id: node.id,
          override_type: 'maintenance',
          start_at: '2026-09-21T08:00:00',
          end_at: '2026-09-21T12:00:00',
          status: 'active',
          reason: '新建检修',
          created_at: '2026-09-20T16:00:00',
        }]
      }
      return { overrides: manager.state.nodeOverrides.value }
    })
    manager.actions.createCalendarOverride.mockImplementation(async () => {
      await manager.actions.loadOverrides(manager.state.productionNodes.value[0])
      return { id: 91 }
    })
    const { wrapper } = mountWorkbench({ manager })
    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await calendarTab.click()
    await flushPromises()

    await wrapper.findComponent(NodeCalendarPanel).get('form').trigger('submit')
    await flushPromises()

    expect(manager.actions.createCalendarOverride).toHaveBeenCalledOnce()
    expect(manager.actions.loadOverrides).toHaveBeenCalledTimes(2)
    expect(manager.actions.loadOverrides).toHaveBeenLastCalledWith(expect.objectContaining({ id: 11 }))
    expect(wrapper.findComponent(NodeCalendarPanel).text()).toContain('新建检修')
  })

  it('keeps node B selected and submits to B after node A finishes a stale slow create', async () => {
    const pendingCreate = deferredCommand()
    productionMocks.listProductionNodes.mockReset().mockResolvedValue({
      nodes: [
        { id: 11, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01', status: 'active', calendar_id: 3 },
        { id: 12, process_id: 8, process_name: '装配', node_code: 'ASSY-01', node_name: '装配-01', status: 'active', calendar_id: 3 },
      ],
    })
    productionMocks.listScheduleCalendars.mockReset().mockResolvedValue({
      calendars: [{ id: 3, calendar_name: '生产九小时日历', daily_minutes: 540 }],
    })
    productionMocks.listProductionNodeCapabilities.mockReset().mockResolvedValue({ capabilities: [] })
    productionMocks.listProductionNodeOverrides
      .mockReset()
      .mockResolvedValueOnce({ overrides: [] })
      .mockResolvedValueOnce({ overrides: [{ id: 81, production_node_id: 11, reason: 'A 初始' }] })
      .mockResolvedValueOnce({ overrides: [{ id: 82, production_node_id: 12, reason: 'B 当前' }] })
      .mockResolvedValueOnce({ overrides: [{ id: 92, production_node_id: 12, reason: 'B 新建' }] })
    productionMocks.createProductionNodeOverride
      .mockReset()
      .mockReturnValueOnce(pendingCreate.promise)
      .mockResolvedValueOnce({ id: 92 })
    const managerState = useProductionNodes({
      canManageNodes: ref(true),
      canManageCapabilities: ref(true),
      canManageCalendars: ref(true),
    })
    await managerState.loadNodes()
    const { wrapper } = mountWorkbench({ manager: managerState.nodeManager })
    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await calendarTab.click()
    await flushPromises()

    const calendarPanel = wrapper.findComponent(NodeCalendarPanel)
    await calendarPanel.get('[data-test="override-start"]').setValue('2026-09-21T08:00')
    await calendarPanel.get('[data-test="override-end"]').setValue('2026-09-21T12:00')
    await calendarPanel.get('[data-test="override-reason"]').setValue('A 慢请求')
    await calendarPanel.get('form').trigger('submit')
    await nextTick()

    await document.body.querySelector('[data-test="node-item-12"]').click()
    await nextTick()
    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(document.body.querySelector('[data-test="node-item-12"]').getAttribute('aria-current')).toBe('true')
    expect(managerState.overrideForm.value.production_node_id).toBe(12)
    expect(managerState.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 82, production_node_id: 12, reason: 'B 当前' }),
    ])

    pendingCreate.resolve({ id: 91 })
    await flushPromises()

    expect(document.body.querySelector('[data-test="node-item-12"]').getAttribute('aria-current')).toBe('true')
    expect(managerState.overrideForm.value.production_node_id).toBe(12)
    expect(managerState.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 82, production_node_id: 12, reason: 'B 当前' }),
    ])

    await calendarPanel.get('[data-test="override-start"]').setValue('2026-09-21T13:00')
    await calendarPanel.get('[data-test="override-end"]').setValue('2026-09-21T17:00')
    await calendarPanel.get('[data-test="override-reason"]').setValue('B 新建')
    await calendarPanel.get('form').trigger('submit')
    await flushPromises()

    expect(productionMocks.createProductionNodeOverride).toHaveBeenLastCalledWith(12, expect.objectContaining({
      reason: 'B 新建',
    }))
    expect(managerState.overrideForm.value.production_node_id).toBe(12)
    expect(wrapper.findComponent(NodeCalendarPanel).text()).toContain('B 新建')
  })

  it('selects a created node after the controller-owned refresh without reloading again', async () => {
    const manager = managerFixture()
    manager.actions.saveNode.mockImplementation(async () => {
      await manager.actions.loadNodes()
      manager.state.productionNodes.value.push({
        id: 21,
        process_id: 7,
        process_name: '焊接',
        node_code: 'WELD-NEW',
        node_name: '新焊接节点',
        status: 'active',
        capacity_mode: 'exclusive',
      })
      return { id: 21 }
    })
    const { wrapper } = mountWorkbench({ manager, props: { processOptions: [{ id: 7, name: '焊接' }] } })

    await document.body.querySelector('[data-test="node-create"]').click()
    await nextTick()
    manager.state.nodeForm.value = {
      id: null,
      process_id: 7,
      node_code: 'WELD-NEW',
      node_name: '新焊接节点',
      capacity_mode: 'exclusive',
      calendar_id: 1,
      status: 'active',
      reason: '新建',
      idempotency_key: 'node-new',
    }
    await nextTick()

    expect(wrapper.findComponent(NodeEditorPanel).exists()).toBe(true)
    await wrapper.findComponent(NodeEditorPanel).get('form').trigger('submit')
    await flushPromises()

    expect(manager.actions.loadNodes).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[data-test="node-item-21"]').getAttribute('aria-current')).toBe('true')
    expect(manager.actions.editNode).toHaveBeenLastCalledWith(expect.objectContaining({ id: 21 }))
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('节点列表')
    expect(document.activeElement).toBe(document.body.querySelector('[role="tab"][aria-selected="true"]'))
    expect(document.body.querySelector('[data-test="node-summary"]').textContent).toContain('新焊接节点')
  })

  it('retains the updated node selection using its pre-save identity when the result omits an id', async () => {
    const manager = managerFixture()
    manager.state.nodeForm.value = {
      id: 11,
      process_id: 7,
      node_code: 'WELD-01',
      node_name: '焊接主节点',
      capacity_mode: 'exclusive',
      calendar_id: 1,
      status: 'active',
      reason: '更新',
      idempotency_key: 'node-11-update',
    }
    manager.actions.saveNode.mockImplementation(async () => {
      await manager.actions.loadNodes()
      return {}
    })
    const { wrapper } = mountWorkbench({ manager })
    const editorTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '节点编辑')

    await editorTab.click()
    await nextTick()
    await wrapper.findComponent(NodeEditorPanel).get('[data-test="node-name"]').setValue('焊接主节点')
    await wrapper.findComponent(NodeEditorPanel).get('form').trigger('submit')
    await flushPromises()

    expect(manager.actions.loadNodes).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[data-test="node-item-11"]').getAttribute('aria-current')).toBe('true')
    expect(manager.actions.editNode).toHaveBeenLastCalledWith(expect.objectContaining({ id: 11 }))
    expect(document.body.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('节点列表')
  })

  it('keeps dirty state and exposes the controller error when the refreshed node is absent', async () => {
    const manager = managerFixture()
    manager.actions.saveNode.mockImplementation(async () => {
      await manager.actions.loadNodes()
      manager.state.productionNodes.value = []
      manager.state.nodesError.value = '保存成功，但刷新节点失败'
      manager.state.nodeForm.value = {
        id: null,
        process_id: '',
        node_code: '',
        node_name: '',
        capacity_mode: 'exclusive',
        calendar_id: '',
        status: 'active',
        reason: '',
        idempotency_key: 'node-next',
      }
      return { id: 99 }
    })
    const { wrapper } = mountWorkbench({ manager })

    await document.body.querySelector('[data-test="node-create"]').click()
    manager.state.nodeForm.value = {
      id: null,
      process_id: 7,
      node_code: 'WELD-MISSING',
      node_name: '待刷新节点',
      capacity_mode: 'exclusive',
      calendar_id: 1,
      status: 'active',
      reason: '新建',
      idempotency_key: 'node-missing',
    }
    await nextTick()
    await wrapper.findComponent(NodeEditorPanel).get('[data-test="node-name"]').setValue('待刷新节点修改')
    await wrapper.findComponent(NodeEditorPanel).get('form').trigger('submit')
    await flushPromises()

    expect(manager.actions.loadNodes).toHaveBeenCalledOnce()
    expect(document.body.textContent).toContain('保存成功，但刷新节点失败')
    expect(document.body.querySelector('[aria-current="true"]')).toBeNull()

    await document.body.querySelector('.node-workbench__footer button').click()
    expect(document.body.querySelector('[role="alertdialog"]')).not.toBeNull()
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
