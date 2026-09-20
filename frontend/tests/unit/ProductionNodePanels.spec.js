import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, reactive, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import NodeCapabilityPanel from '@/components/production-nodes/NodeCapabilityPanel.vue'
import nodeCapabilityPanelSource from '@/components/production-nodes/NodeCapabilityPanel.vue?raw'
import NodeCalendarPanel from '@/components/production-nodes/NodeCalendarPanel.vue'
import nodeCalendarPanelSource from '@/components/production-nodes/NodeCalendarPanel.vue?raw'
import NodeEditorPanel from '@/components/production-nodes/NodeEditorPanel.vue'
import ProductionNodeWorkbench from '@/components/production-nodes/ProductionNodeWorkbench.vue'

function deferred() {
  let resolve
  const promise = new Promise(resolvePromise => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

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

function capabilityFormFixture(overrides = {}) {
  return reactive({
    production_node_id: 11,
    node_label: 'WELD-01 · 焊接-01',
    capabilities: [{
      product_id: null,
      product_family: 'HOUSING',
      material_code: '',
      specification: '',
      route_version_id: null,
      process_version_id: null,
      max_batch_quantity: null,
      batch_minutes: null,
      changeover_minutes: 0,
      allow_mixed_orders: false,
      status: 'active',
    }],
    reason: '',
    idempotency_key: 'capability-11',
    ...overrides,
  })
}

function mountCapabilities(options = {}) {
  return mount(NodeCapabilityPanel, {
    props: {
      node: { id: 11, node_code: 'WELD-01', node_name: '焊接-01', capacity_mode: 'exclusive' },
      form: options.form || capabilityFormFixture(),
      loading: false,
      error: '',
      saving: false,
      canManage: true,
      onAdd: vi.fn(),
      onRemove: vi.fn(),
      onSave: vi.fn(),
      onRetry: vi.fn(),
      ...options.props,
    },
  })
}

describe('NodeCapabilityPanel', () => {
  it('shows batch fields only for batch nodes and preserves capability rows on save failure', async () => {
    const form = capabilityFormFixture()
    const onSave = vi.fn().mockResolvedValue(null)
    const wrapper = mountCapabilities({ form, props: { onSave } })

    expect(wrapper.find('[data-test="batch-minutes"]').exists()).toBe(false)
    await wrapper.get('[data-test="capability-product-family"]').setValue('SB121')
    await wrapper.get('[data-test="capability-reason"]').setValue('更新产品族')
    await wrapper.get('form').trigger('submit')

    expect(form.capabilities[0].product_family).toBe('SB121')
    expect(form.reason).toBe('更新产品族')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])
    expect(wrapper.emitted('saved')).toBeUndefined()

    await wrapper.setProps({ node: { id: 11, capacity_mode: 'batch' } })
    expect(wrapper.find('[data-test="batch-minutes"]').exists()).toBe(true)
  })

  it('binds every capability field to the manager form and delegates row actions', async () => {
    const form = capabilityFormFixture()
    const onAdd = vi.fn()
    const onRemove = vi.fn()
    const wrapper = mountCapabilities({
      form,
      props: { node: { id: 11, capacity_mode: 'batch' }, onAdd, onRemove },
    })

    await wrapper.get('[data-test="capability-product-id"]').setValue('101')
    await wrapper.get('[data-test="capability-product-family"]').setValue('SB121')
    await wrapper.get('[data-test="capability-material-code"]').setValue('MAT-01')
    await wrapper.get('[data-test="capability-specification"]').setValue('20mm')
    await wrapper.get('[data-test="capability-route-version-id"]').setValue('201')
    await wrapper.get('[data-test="capability-process-version-id"]').setValue('301')
    await wrapper.get('[data-test="max-batch-quantity"]').setValue('50')
    await wrapper.get('[data-test="batch-minutes"]').setValue('90')
    await wrapper.get('[data-test="changeover-minutes"]').setValue('15')
    await wrapper.get('[data-test="allow-mixed-orders"]').setValue(true)
    await wrapper.get('[data-test="capability-status"]').setValue('inactive')
    await wrapper.get('[data-test="capability-add"]').trigger('click')
    await wrapper.get('[data-test="capability-remove"]').trigger('click')

    expect(form.capabilities[0]).toMatchObject({
      product_id: 101,
      product_family: 'SB121',
      material_code: 'MAT-01',
      specification: '20mm',
      route_version_id: 201,
      process_version_id: 301,
      max_batch_quantity: 50,
      batch_minutes: 90,
      changeover_minutes: 15,
      allow_mixed_orders: true,
      status: 'inactive',
    })
    expect(onAdd).toHaveBeenCalledOnce()
    expect(onRemove).toHaveBeenCalledWith(0)
  })

  it('closes loading, error, retry, successful save, and slow-submit states', async () => {
    const pending = deferred()
    const onRetry = vi.fn()
    const form = capabilityFormFixture()
    const wrapper = mountCapabilities({
      form,
      props: { error: '能力读取失败', onRetry, onSave: vi.fn(() => pending.promise) },
    })

    expect(wrapper.get('[role="alert"]').text()).toContain('能力读取失败')
    expect(wrapper.get('[data-test="capability-fields"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="capability-retry"]').trigger('click')
    expect(onRetry).toHaveBeenCalledOnce()

    await wrapper.setProps({ error: '', loading: true })
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载')
    await wrapper.setProps({ loading: false })
    await wrapper.get('[data-test="capability-reason"]').setValue('更新能力')
    await wrapper.get('form').trigger('submit')
    await nextTick()

    expect(wrapper.get('[data-test="capability-fields"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="capability-add"]').attributes('disabled')).toBeDefined()
    pending.resolve({ capabilities: [] })
    await flushPromises()

    expect(wrapper.emitted('saved')).toEqual([[{ capabilities: [] }]])
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([false])
    expect(wrapper.get('[data-test="capability-fields"]').attributes('disabled')).toBeUndefined()
  })

  it('renders capability summaries without modification controls for read-only users', () => {
    const wrapper = mountCapabilities({
      form: capabilityFormFixture({
        capabilities: [{
          product_id: 101,
          product_family: 'READ-ONLY',
          material_code: 'MAT-01',
          specification: '20mm',
          route_version_id: 201,
          process_version_id: 301,
          max_batch_quantity: 50,
          batch_minutes: 90,
          changeover_minutes: 15,
          allow_mixed_orders: true,
          status: 'active',
        }],
      }),
      props: { node: { id: 11, capacity_mode: 'batch' }, canManage: false },
    })

    expect(wrapper.get('[data-test="capability-row"]').text()).toContain('READ-ONLY')
    expect(wrapper.get('[data-test="capability-row"]').text()).toContain('MAT-01')
    expect(wrapper.get('[data-test="capability-row"]').text()).toContain('90')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.find('[data-test="capability-add"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="capability-remove"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="capability-save"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="capability-reason"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="capability-idempotency-key"]').exists()).toBe(false)
  })

  it('clears dirty state only after save replaces the manager form with refreshed data', async () => {
    const editedForm = capabilityFormFixture()
    const refreshedForm = capabilityFormFixture({
      capabilities: [{
        ...editedForm.capabilities[0],
        product_family: 'REFRESHED',
      }],
      reason: '',
      idempotency_key: 'capability-11-refreshed',
    })
    let wrapper
    const onSave = vi.fn(async () => {
      await wrapper.setProps({ form: refreshedForm })
      return { capabilities: refreshedForm.capabilities }
    })
    wrapper = mountCapabilities({ form: editedForm, props: { onSave } })

    await wrapper.get('[data-test="capability-product-family"]').setValue('EDITED')
    await wrapper.get('[data-test="capability-reason"]').setValue('更新能力')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[data-test="capability-product-family"]').element.value).toBe('REFRESHED')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([false])
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('uses only the shared 899px responsive boundary', () => {
    expect(nodeCapabilityPanelSource).toContain('@media (max-width: 899px)')
    expect(nodeCapabilityPanelSource.match(/@media/g)).toHaveLength(1)
  })
})

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

  it('preserves dirty input after a failed save and emits the pre-save identity after success', async () => {
    const form = formFixture()
    const onSave = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce({ id: 11 })
    const wrapper = mountEditor({ form, props: { onSave } })

    await wrapper.get('[data-test="node-name"]').setValue('焊接主节点')
    await wrapper.get('form').trigger('submit')
    expect(form.node_name).toBe('焊接主节点')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])
    expect(wrapper.emitted('saved')).toBeUndefined()

    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])
    expect(wrapper.emitted('saved')).toEqual([[{ id: 11 }, { id: 11, node_code: 'WELD-01' }]])
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

describe('NodeCalendarPanel', () => {
  it('uses the workbench-wide 899px responsive boundary without a second breakpoint', () => {
    expect(nodeCalendarPanelSource).toContain('@media (max-width: 899px)')
    expect(nodeCalendarPanelSource).not.toMatch(/max-width:\s*699px/)
  })

  it('derives effective minutes from the calendar shifts returned by the schedule API', () => {
    const wrapper = mount(NodeCalendarPanel, {
      props: {
        node: { id: 11, calendar_id: 3 },
        calendar: {
          id: 3,
          calendar_name: '生产九小时日历',
          shifts: [
            { start_minute: 480, end_minute: 720 },
            { start_minute: 780, end_minute: 1080 },
          ],
        },
        overrides: [],
        form: {
          production_node_id: 11,
          start_at: '',
          end_at: '',
          override_type: 'maintenance',
          reason: '',
          idempotency_key: 'calendar-11',
        },
        loading: false,
        error: '',
        saving: false,
        canManage: true,
        onRetry: vi.fn(),
        onSave: vi.fn(),
        onCancelOverride: vi.fn(),
      },
    })

    expect(wrapper.text()).toContain('540 分钟')
  })

  it('renders the base calendar, retries failed loads, and creates an override', async () => {
    const onRetry = vi.fn()
    const onSave = vi.fn().mockResolvedValue({ id: 91 })
    const wrapper = mount(NodeCalendarPanel, {
      props: {
        node: { id: 11, calendar_id: 3 },
        calendar: { id: 3, calendar_name: '生产九小时日历', daily_minutes: 540 },
        overrides: [],
        form: {
          production_node_id: 11,
          start_at: '',
          end_at: '',
          override_type: 'maintenance',
          reason: '',
          idempotency_key: 'calendar-11',
        },
        loading: false,
        error: '日历读取失败',
        saving: false,
        canManage: true,
        onRetry,
        onSave,
        onCancelOverride: vi.fn(),
      },
    })

    expect(wrapper.text()).toContain('生产九小时日历')
    expect(wrapper.text()).toContain('540')
    await wrapper.get('[data-test="calendar-retry"]').trigger('click')
    expect(onRetry).toHaveBeenCalled()

    await wrapper.get('[data-test="override-start"]').setValue('2026-09-21T08:00')
    await wrapper.get('[data-test="override-end"]').setValue('2026-09-21T12:00')
    await wrapper.get('[data-test="override-reason"]').setValue('计划检修')
    await wrapper.get('form').trigger('submit')

    expect(onSave).toHaveBeenCalledOnce()
    expect(wrapper.emitted('saved')).toEqual([[{ id: 91 }]])
  })

  it('orders overrides newest first and delegates cancellation', async () => {
    const onCancelOverride = vi.fn()
    const older = {
      id: 81,
      production_node_id: 11,
      override_type: 'unavailable',
      start_at: '2026-09-20T08:00:00',
      end_at: '2026-09-20T10:00:00',
      status: 'active',
      reason: '早期停机',
      created_at: '2026-09-18T08:00:00',
    }
    const newer = {
      id: 82,
      production_node_id: 11,
      override_type: 'maintenance',
      start_at: '2026-09-21T08:00:00',
      end_at: '2026-09-21T10:00:00',
      status: 'cancelled',
      reason: '最新检修',
      created_at: '2026-09-19T08:00:00',
    }
    const wrapper = mount(NodeCalendarPanel, {
      props: {
        node: { id: 11, calendar_id: 3 },
        calendar: { id: 3, calendar_name: '生产九小时日历', daily_minutes: 540 },
        overrides: [older, newer],
        form: {
          production_node_id: 11,
          start_at: '',
          end_at: '',
          override_type: 'maintenance',
          reason: '',
          idempotency_key: 'calendar-11',
        },
        loading: false,
        error: '',
        saving: false,
        canManage: true,
        onRetry: vi.fn(),
        onSave: vi.fn(),
        onCancelOverride,
      },
    })

    const rows = wrapper.findAll('[data-test="override-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('最新检修')
    expect(rows[1].text()).toContain('早期停机')
    await rows[1].get('[data-test="override-cancel"]').trigger('click')
    expect(onCancelOverride).toHaveBeenCalledWith(older)
  })

  it('emits dirty state from the local form digest and resets it after a successful save', async () => {
    const onSave = vi.fn().mockResolvedValue({ id: 91 })
    const wrapper = mount(NodeCalendarPanel, {
      props: {
        node: { id: 11, calendar_id: 3 },
        calendar: null,
        overrides: [],
        form: {
          production_node_id: 11,
          start_at: '',
          end_at: '',
          override_type: 'maintenance',
          reason: '',
          idempotency_key: 'calendar-11',
        },
        loading: false,
        error: '',
        saving: false,
        canManage: true,
        onRetry: vi.fn(),
        onSave,
        onCancelOverride: vi.fn(),
      },
    })

    await wrapper.get('[data-test="override-reason"]').setValue('计划检修')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])

    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('saved')).toEqual([[{ id: 91 }]])
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([false])
  })

  it('disables the whole form during a slow save and preserves dirty input after failure', async () => {
    const pending = deferred()
    const form = reactive({
      production_node_id: 11,
      start_at: '2026-09-21T08:00',
      end_at: '2026-09-21T12:00',
      override_type: 'maintenance',
      reason: '',
      idempotency_key: 'calendar-11',
    })
    const wrapper = mount(NodeCalendarPanel, {
      props: {
        node: { id: 11, calendar_id: 3 },
        calendar: null,
        overrides: [],
        form,
        loading: false,
        error: '',
        saving: false,
        canManage: true,
        onRetry: vi.fn(),
        onSave: vi.fn(() => pending.promise),
        onCancelOverride: vi.fn(),
      },
    })

    await wrapper.get('[data-test="override-reason"]').setValue('慢请求检修')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])

    await wrapper.get('form').trigger('submit')
    await nextTick()

    expect(wrapper.get('[data-test="override-fields"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="override-reason"]').element.matches(':disabled')).toBe(true)

    pending.resolve(null)
    await flushPromises()

    expect(wrapper.get('[data-test="override-fields"]').attributes('disabled')).toBeUndefined()
    expect(form.reason).toBe('慢请求检修')
    expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])
    expect(wrapper.emitted('saved')).toBeUndefined()
  })
})

function calendarWorkbenchManager() {
  return {
    state: {
      productionNodes: ref([
        { id: 11, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01', status: 'active', calendar_id: 3 },
        { id: 12, process_id: 8, process_name: '装配', node_code: 'ASSY-01', node_name: '装配-01', status: 'active', calendar_id: 3 },
      ]),
      productionCalendars: ref([{ id: 3, calendar_name: '生产九小时日历', daily_minutes: 540 }]),
      nodesLoading: ref(false),
      nodesError: ref(''),
      nodeForm: ref({}),
      nodeSaving: ref(false),
      overrideForm: ref({
        production_node_id: 11,
        start_at: '',
        end_at: '',
        override_type: 'maintenance',
        reason: '',
        idempotency_key: 'calendar-11',
      }),
      nodeOverrides: ref([]),
      overridesLoading: ref(false),
      overridesError: ref(''),
      overrideSaving: ref(false),
      capabilityForm: ref(capabilityFormFixture()),
      capabilitiesLoading: ref(false),
      capabilitiesError: ref(''),
      capabilitySaving: ref(false),
    },
    permissions: {
      canManageNodes: ref(true),
      canManageCalendars: ref(true),
      canManageCapabilities: ref(true),
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

describe('ProductionNodeWorkbench calendar integration', () => {
  it('loads calendar data only on tab entry and reloads it after a node change', async () => {
    const manager = calendarWorkbenchManager()
    const wrapper = mount(ProductionNodeWorkbench, {
      props: { modelValue: true, manager },
      attachTo: document.body,
    })
    await nextTick()

    expect(manager.actions.prepareOverride).not.toHaveBeenCalled()
    expect(manager.actions.loadOverrides).not.toHaveBeenCalled()

    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await calendarTab.click()
    await flushPromises()

    expect(wrapper.findComponent(NodeCalendarPanel).exists()).toBe(true)
    expect(manager.actions.prepareOverride).toHaveBeenLastCalledWith(expect.objectContaining({ id: 11 }))
    expect(manager.actions.loadOverrides).toHaveBeenLastCalledWith(expect.objectContaining({ id: 11 }))

    await document.body.querySelector('[data-test="node-item-12"]').click()
    await flushPromises()

    expect(manager.actions.prepareOverride).toHaveBeenCalledTimes(2)
    expect(manager.actions.prepareOverride).toHaveBeenLastCalledWith(expect.objectContaining({ id: 12 }))
    expect(manager.actions.loadOverrides).toHaveBeenCalledTimes(2)
    expect(manager.actions.loadOverrides).toHaveBeenLastCalledWith(expect.objectContaining({ id: 12 }))

    wrapper.unmount()
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })

  it('guards a node change while the calendar form is dirty', async () => {
    const manager = calendarWorkbenchManager()
    const wrapper = mount(ProductionNodeWorkbench, {
      props: { modelValue: true, manager },
      attachTo: document.body,
    })
    const calendarTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '工作日历')
    await calendarTab.click()
    await flushPromises()

    await wrapper.findComponent(NodeCalendarPanel).get('[data-test="override-reason"]').setValue('未保存检修')
    await document.body.querySelector('[data-test="node-item-12"]').click()
    await nextTick()

    expect(document.body.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(document.body.querySelector('[data-test="node-item-11"]').getAttribute('aria-current')).toBe('true')
    expect(manager.actions.loadOverrides).toHaveBeenCalledTimes(1)

    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(document.body.querySelector('[data-test="node-item-12"]').getAttribute('aria-current')).toBe('true')
    expect(manager.actions.loadOverrides).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })
})

describe('ProductionNodeWorkbench capability integration', () => {
  it('loads capabilities only on tab entry and shares guarded node selection with the workbench', async () => {
    const manager = calendarWorkbenchManager()
    const wrapper = mount(ProductionNodeWorkbench, {
      props: { modelValue: true, manager },
      attachTo: document.body,
    })
    await nextTick()

    expect(manager.actions.loadCapabilities).not.toHaveBeenCalled()
    const capabilityTab = [...document.body.querySelectorAll('[role="tab"]')]
      .find(tab => tab.textContent === '能力限制')
    await capabilityTab.click()
    await flushPromises()

    expect(wrapper.findComponent(NodeCapabilityPanel).exists()).toBe(true)
    expect(manager.actions.loadCapabilities).toHaveBeenLastCalledWith(expect.objectContaining({ id: 11 }))

    await wrapper.findComponent(NodeCapabilityPanel).get('[data-test="capability-reason"]').setValue('未保存能力')
    await document.body.querySelector('[data-test="node-item-12"]').click()
    await nextTick()

    expect(document.body.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(manager.actions.loadCapabilities).toHaveBeenCalledTimes(1)
    expect(document.body.querySelector('[data-test="node-item-11"]').getAttribute('aria-current')).toBe('true')

    const discard = [...document.body.querySelectorAll('.node-discard-dialog button')]
      .find(button => button.textContent === '放弃更改')
    await discard.click()
    await flushPromises()

    expect(manager.actions.loadCapabilities).toHaveBeenCalledTimes(2)
    expect(manager.actions.loadCapabilities).toHaveBeenLastCalledWith(expect.objectContaining({ id: 12 }))
    expect(document.body.querySelector('[data-test="node-item-12"]').getAttribute('aria-current')).toBe('true')

    manager.state.capabilitiesError.value = '能力读取失败'
    await nextTick()
    await wrapper.findComponent(NodeCapabilityPanel).get('[data-test="capability-retry"]').trigger('click')
    expect(manager.actions.loadCapabilities).toHaveBeenLastCalledWith(expect.objectContaining({ id: 12 }))

    wrapper.unmount()
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })
})
