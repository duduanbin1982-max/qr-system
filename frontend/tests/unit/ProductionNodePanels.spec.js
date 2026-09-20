import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, reactive, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import NodeCalendarPanel from '@/components/production-nodes/NodeCalendarPanel.vue'
import NodeEditorPanel from '@/components/production-nodes/NodeEditorPanel.vue'
import ProductionNodeWorkbench from '@/components/production-nodes/ProductionNodeWorkbench.vue'

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
    },
    permissions: {
      canManageNodes: ref(true),
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
