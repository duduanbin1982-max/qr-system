import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import ApprovalPage from '@/views/ApprovalPage.vue'

const mocks = vi.hoisted(() => ({
  history: vi.fn(), pending: vi.fn(), stats: vi.fn(), toast: vi.fn(),
}))
vi.mock('@/lib/api.js', () => ({
  api: { domains: { approvals: {
    approvalHistory: mocks.history, pendingApprovals: mocks.pending, approvalStats: mocks.stats,
  } } },
}))
vi.mock('@/lib/auth.js', () => ({ can: () => false }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))

let wrapper
beforeEach(() => {
  vi.resetAllMocks()
  mocks.pending.mockResolvedValue({ approvals: [], total: 0, page: 1, limit: 20 })
  mocks.stats.mockResolvedValue({ avg_hours: 0, pending_over_24h: 0 })
})
afterEach(() => wrapper?.unmount())

function response(page, limit, total, order = `PAGE-${page}`) {
  return { page, limit, total, approvals: total ? [{ id: page, order_no: order, status: 'approved' }] : [] }
}
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function button(text) {
  return wrapper.findAll('button').find(item => item.text() === text)
}
async function openHistory(data) {
  mocks.history.mockResolvedValueOnce(data)
  wrapper = mount(ApprovalPage)
  await flushPromises()
  await button('📋 审批历史').trigger('click')
  await flushPromises()
}

describe('approval history pagination', () => {
  it.each([10, 20, 50])('uses returned limit %i for page count and navigation', async limit => {
    await openHistory(response(1, limit, limit + 1))
    expect(mocks.history).toHaveBeenCalledWith({ page: 1, limit: 20 })
    expect(wrapper.text()).toContain('第 1 / 2 页')
    mocks.history.mockResolvedValueOnce(response(2, limit, limit + 1))
    await button('下一页').trigger('click')
    await flushPromises()
    expect(mocks.history).toHaveBeenLastCalledWith({ page: 2, limit })
    expect(wrapper.text()).toContain('PAGE-2')
    expect(button('下一页').attributes('disabled')).toBeDefined()
    expect(button('上一页').attributes('disabled')).toBeUndefined()
    mocks.history.mockResolvedValueOnce(response(1, limit, limit + 1))
    await button('上一页').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 1 / 2 页')
    expect(button('上一页').attributes('disabled')).toBeDefined()
  })

  it.each([0, 10, 20, 50])('has no unnecessary next page for total %i', async total => {
    await openHistory(response(1, Math.max(10, total), total))
    expect(button('下一页')).toBeUndefined()
    if (!total) expect(wrapper.text()).toContain('暂无审批记录')
  })

  it('keeps successful rows and page when navigation fails', async () => {
    await openHistory(response(1, 20, 41))
    const pending = deferred()
    mocks.history.mockReturnValueOnce(pending.promise)
    await button('下一页').trigger('click')
    expect(wrapper.vm.historyPage).toBe(1)
    expect(button('下一页').attributes('disabled')).toBeDefined()
    await button('下一页').trigger('click')
    expect(mocks.history).toHaveBeenCalledTimes(2)
    pending.reject(new Error('history unavailable'))
    await flushPromises()
    expect(wrapper.text()).toContain('PAGE-1')
    expect(wrapper.text()).toContain('第 1 / 3 页')
    expect(mocks.toast).toHaveBeenCalledWith('history unavailable', 'error')
  })

  it.each(['resolve', 'reject'])('ignores stale %s after a newer response', async outcome => {
    await openHistory(response(1, 20, 60))
    const stale = deferred(), latest = deferred()
    mocks.history.mockReturnValueOnce(stale.promise).mockReturnValueOnce(latest.promise)
    const first = wrapper.vm.loadHistory(2)
    const second = wrapper.vm.loadHistory(3)
    latest.resolve(response(3, 10, 60, 'NEWEST'))
    await second
    stale[outcome](outcome === 'resolve' ? response(2, 20, 60, 'STALE') : new Error('stale failure'))
    await first
    await flushPromises()
    expect(wrapper.vm.historyPage).toBe(3)
    expect(wrapper.text()).toContain('NEWEST')
    expect(wrapper.text()).not.toContain('STALE')
    expect(mocks.toast).not.toHaveBeenCalled()
  })

  it('does not clear loading when an older request completes first', async () => {
    await openHistory(response(1, 20, 60))
    const stale = deferred(), latest = deferred()
    mocks.history.mockReturnValueOnce(stale.promise).mockReturnValueOnce(latest.promise)
    const first = wrapper.vm.loadHistory(2)
    const second = wrapper.vm.loadHistory(3)
    stale.resolve(response(2, 20, 60))
    await first
    expect(wrapper.vm.historyLoading).toBe(true)
    latest.resolve(response(3, 20, 60))
    await second
    expect(wrapper.vm.historyLoading).toBe(false)
  })
})
