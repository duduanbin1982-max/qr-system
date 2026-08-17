import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuditLogs } from '@/composables/settings/useAuditLogs.js'


const mocks = vi.hoisted(() => ({
  listLogs: vi.fn(),
  listCategories: vi.fn(),
  listCleanupRequests: vi.fn(),
  deleteLogs: vi.fn(),
  approveCleanupRequest: vi.fn(),
  rejectCleanupRequest: vi.fn(),
  can: vi.fn(),
  auth: { user: { id: 10 } },
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { logs: {
    listLogs: mocks.listLogs,
    listCategories: mocks.listCategories,
    listCleanupRequests: mocks.listCleanupRequests,
    deleteLogs: mocks.deleteLogs,
    approveCleanupRequest: mocks.approveCleanupRequest,
    rejectCleanupRequest: mocks.rejectCleanupRequest,
  } } },
}))
vi.mock('@/lib/auth.js', () => ({ auth: mocks.auth, can: mocks.can }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


function mountHarness() {
  let auditLogs
  const harness = defineComponent({
    setup() {
      auditLogs = useAuditLogs()
      return () => h('div')
    },
  })
  return {
    wrapper: mount(harness),
    get auditLogs() { return auditLogs },
  }
}


describe('useAuditLogs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.auth.user = { id: 10 }
    mocks.can.mockReturnValue(true)
    mocks.listLogs.mockResolvedValue({ logs: [], total: 0 })
    mocks.listCategories.mockResolvedValue({ items: [{ code: 'system', label: '系统配置' }] })
    mocks.listCleanupRequests.mockResolvedValue({ items: [] })
    mocks.deleteLogs.mockResolvedValue({ affected_count: 3 })
    mocks.approveCleanupRequest.mockResolvedValue({ archived: 3, deleted: 3 })
    mocks.rejectCleanupRequest.mockResolvedValue({})
  })

  it('loads category metadata and admin cleanup requests', async () => {
    const harness = mountHarness()
    await flushPromises()

    expect(mocks.listLogs).toHaveBeenCalledTimes(1)
    expect(mocks.listCategories).toHaveBeenCalledTimes(1)
    expect(mocks.listCleanupRequests).toHaveBeenCalledWith({ limit: 100 })
    expect(harness.auditLogs.canClearLogs.value).toBe(true)
    expect(harness.auditLogs.logCategories.value[0].code).toBe('system')
    harness.wrapper.unmount()
  })

  it('does not load cleanup requests for a read-only log viewer', async () => {
    mocks.can.mockImplementation(permission => permission === 'logs:view')
    const harness = mountHarness()
    await flushPromises()

    expect(harness.auditLogs.canClearLogs.value).toBe(false)
    expect(mocks.listCleanupRequests).not.toHaveBeenCalled()
    harness.wrapper.unmount()
  })

  it('submits a reasoned three-year cleanup request', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(window, 'prompt').mockReturnValue('超过保留期')
    const harness = mountHarness()
    await flushPromises()

    await harness.auditLogs.clearLogs(1095)

    expect(mocks.deleteLogs).toHaveBeenCalledWith({
      before_days: 1095,
      reason: '超过保留期',
    })
    expect(mocks.showToast).toHaveBeenCalledWith('清理申请已提交，预计影响 3 条日志')
    harness.wrapper.unmount()
  })

  it('prevents the requester from reviewing their own request', async () => {
    const harness = mountHarness()
    await flushPromises()

    expect(harness.auditLogs.canReviewCleanup({ status: 'pending', requested_by: 10 })).toBe(false)
    expect(harness.auditLogs.canReviewCleanup({ status: 'pending', requested_by: 11 })).toBe(true)
    harness.wrapper.unmount()
  })
})
