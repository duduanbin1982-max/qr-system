import { mount } from '@vue/test-utils'
import { computed, reactive, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProcessConfig from '@/views/settings/ProcessConfig.vue'


const mocks = vi.hoisted(() => ({
  state: null,
  showToast: vi.fn(),
  auth: { user: { id: 101, name: '制单人' } },
}))

vi.mock('@/composables/settings/useProcessConfig.js', () => ({
  useProcessConfig: () => mocks.state,
}))
vi.mock('@/lib/auth.js', () => ({ auth: mocks.auth }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

function stateFor({ openRevision = null } = {}) {
  const current = ref({
    version: 4,
    row_version: 9,
    process_order_mode: 'sequential',
    serial_process_report_mode: 'strict',
    limit_by_prev_process: 1,
    limit_by_order_qty: 1,
    approval_enabled: 1,
    updated_at: '2026-08-17 09:00:00',
    updated_by_name: '管理员',
  })
  const open = ref(openRevision)
  const form = reactive({
    process_order_mode: openRevision?.process_order_mode || 'sequential',
    serial_process_report_mode: openRevision?.serial_process_report_mode || 'strict',
    limit_by_prev_process: openRevision?.limit_by_prev_process ?? 1,
    limit_by_order_qty: openRevision?.limit_by_order_qty ?? 1,
    approval_enabled: openRevision?.approval_enabled ?? 1,
  })
  return {
    config: current,
    current: computed(() => current.value),
    openRevision: open,
    draft: computed(() => open.value?.status === 'draft' ? open.value : null),
    pending: computed(() => open.value?.status === 'pending_approval' ? open.value : null),
    revisions: ref([]),
    form,
    revisionReason: ref(openRevision?.revision_reason || ''),
    loading: ref(false),
    historyLoading: ref(false),
    busy: ref(false),
    operationError: ref(''),
    canCreate: ref(true),
    canSubmit: ref(true),
    canApprove: ref(true),
    canReject: ref(true),
    canEditDraft: computed(() => !open.value || open.value.created_by === 101),
    isDraftOwner: computed(() => open.value?.created_by === 101),
    configValuesDirty: ref(false),
    processConfigDirty: ref(false),
    loadProcessConfig: vi.fn(),
    loadHistory: vi.fn(),
    saveDraft: vi.fn(),
    submitRevision: vi.fn(),
    approveRevision: vi.fn(),
    rejectRevision: vi.fn(),
    discardChanges: vi.fn(),
    processConfigStatusLabel: status => ({ draft: '草稿', pending_approval: '待审批' }[status] || status),
    hasUnsavedChanges: () => false,
  }
}

describe('ProcessConfig view', () => {
  beforeEach(() => {
    mocks.showToast.mockReset()
    mocks.state = stateFor()
  })

  it('exposes only the five process policy fields and removes unrelated settings', () => {
    const wrapper = mount(ProcessConfig)

    expect(wrapper.text()).toContain('工序报工顺序')
    expect(wrapper.text()).toContain('序列号报工规则')
    expect(wrapper.text()).toContain('上道工序累计上限')
    expect(wrapper.text()).toContain('订单总数上限')
    expect(wrapper.text()).toContain('报工审批')
    expect(wrapper.text()).not.toContain('交期预警天数')
    expect(wrapper.text()).not.toContain('列表每页条数')
    expect(wrapper.text()).not.toContain('自动生成订单号前缀')
    wrapper.unmount()
  })

  it('does not show self-approval action for a pending revision', () => {
    mocks.state = stateFor({
      openRevision: {
        id: 11,
        version: 5,
        status: 'pending_approval',
        created_by: 101,
        created_by_name: '制单人',
        revision_reason: '待审批策略',
        process_order_mode: 'out_of_order',
        serial_process_report_mode: 'strict',
        limit_by_prev_process: 0,
        limit_by_order_qty: 1,
        approval_enabled: 1,
      },
    })
    const wrapper = mount(ProcessConfig)

    expect(wrapper.text()).toContain('制单人不能审批或驳回自己的修订版')
    expect(wrapper.findAll('button').some(button => button.text() === '批准并发布')).toBe(false)
    wrapper.unmount()
  })
})
