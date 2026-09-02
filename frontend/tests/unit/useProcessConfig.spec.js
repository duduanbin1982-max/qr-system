import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  processConfigErrorMessage,
  useProcessConfig,
} from '@/composables/settings/useProcessConfig.js'


const mocks = vi.hoisted(() => ({
  getProcessConfig: vi.fn(),
  getProcessConfigHistory: vi.fn(),
  createProcessConfigRevision: vi.fn(),
  updateProcessConfigRevision: vi.fn(),
  submitProcessConfigRevision: vi.fn(),
  approveProcessConfigRevision: vi.fn(),
  rejectProcessConfigRevision: vi.fn(),
  can: vi.fn(),
  showToast: vi.fn(),
  auth: { user: { id: 101, name: '制单人' } },
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { settings: mocks } },
}))
vi.mock('@/lib/auth.js', () => ({ can: mocks.can, auth: mocks.auth }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

const active = {
  id: 1,
  version: 4,
  row_version: 9,
  process_order_mode: 'sequential',
  serial_process_report_mode: 'strict',
  limit_by_prev_process: 1,
  limit_by_order_qty: 1,
  approval_enabled: 1,
}

function payload(overrides = {}) {
  return { config: { ...active, ...overrides }, open_revision: null }
}

function mountHarness() {
  let state
  const harness = defineComponent({
    setup() {
      state = useProcessConfig()
      return () => h('div')
    },
  })
  return { wrapper: mount(harness), get state() { return state } }
}

describe('useProcessConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.can.mockImplementation(permission => [
      'process_config:view',
      'process_config:create',
      'process_config:submit',
      'process_config:approve',
      'process_config:reject',
      'process_config:history',
    ].includes(permission))
    mocks.getProcessConfig.mockResolvedValue(payload({
      limit_by_prev_process: 0,
      limit_by_order_qty: 0,
      approval_enabled: 0,
    }))
    mocks.getProcessConfigHistory.mockResolvedValue({ revisions: [] })
    mocks.createProcessConfigRevision.mockResolvedValue({
      id: 11,
      version: 5,
      status: 'draft',
      row_version: 0,
      created_by: 101,
      ...active,
    })
    mocks.updateProcessConfigRevision.mockResolvedValue({})
    mocks.submitProcessConfigRevision.mockResolvedValue({})
    mocks.approveProcessConfigRevision.mockResolvedValue({})
    mocks.rejectProcessConfigRevision.mockResolvedValue({})
  })

  it('loads scoped data without converting valid zero flags to one', async () => {
    const harness = mountHarness()
    await flushPromises()

    expect(harness.state.form.limit_by_prev_process).toBe(0)
    expect(harness.state.form.limit_by_order_qty).toBe(0)
    expect(harness.state.form.approval_enabled).toBe(0)
    expect(mocks.getProcessConfigHistory).toHaveBeenCalledWith(100)
    harness.wrapper.unmount()
  })

  it('creates a draft with the active row version and a command key', async () => {
    const harness = mountHarness()
    await flushPromises()
    harness.state.form.process_order_mode = 'out_of_order'
    harness.state.form.limit_by_prev_process = 0
    harness.state.revisionReason.value = '启用受控跨工序补报'

    await harness.state.saveDraft()

    expect(mocks.createProcessConfigRevision).toHaveBeenCalledWith(expect.objectContaining({
      row_version: 9,
      process_order_mode: 'out_of_order',
      limit_by_prev_process: 0,
      revision_reason: '启用受控跨工序补报',
      idempotency_key: expect.stringMatching(/^process-config-create:/),
    }))
    harness.wrapper.unmount()
  })

  it('uses draft row versions for update and submit, then a different actor for approval', async () => {
    const draft = {
      ...active,
      id: 11,
      version: 5,
      status: 'draft',
      row_version: 2,
      created_by: 101,
      created_by_name: '制单人',
      revision_reason: '草稿策略',
    }
    mocks.getProcessConfig.mockResolvedValue({ config: active, open_revision: draft })
    const harness = mountHarness()
    await flushPromises()
    harness.state.form.limit_by_order_qty = 0
    await harness.state.updateDraft()
    expect(mocks.updateProcessConfigRevision).toHaveBeenCalledWith(11, expect.objectContaining({
      row_version: 2,
      limit_by_order_qty: 0,
      idempotency_key: expect.stringMatching(/^process-config-update:/),
    }))

    await harness.state.submitRevision()
    expect(mocks.submitProcessConfigRevision).toHaveBeenCalledWith(11, expect.objectContaining({
      row_version: 2,
      idempotency_key: expect.stringMatching(/^process-config-submit:/),
    }))
    harness.wrapper.unmount()
  })

  it('maps workflow actions and preserves a conflict message after refresh', async () => {
    expect(processConfigErrorMessage({ action: 'reload_process_config' })).toContain('刷新当前版本')
    expect(processConfigErrorMessage({ action: 'select_different_approver' })).toContain('切换批准账号')
    const stale = new Error('已过期')
    stale.status = 409
    stale.action = 'reload_process_config'
    mocks.createProcessConfigRevision.mockRejectedValue(stale)
    const harness = mountHarness()
    await flushPromises()
    harness.state.form.limit_by_order_qty = 0
    harness.state.revisionReason.value = '并发测试'
    await expect(harness.state.saveDraft()).rejects.toBe(stale)
    expect(harness.state.operationError.value).toContain('刷新当前版本')
    expect(harness.state.conflict.value).toBe(true)
    harness.wrapper.unmount()
  })
})
