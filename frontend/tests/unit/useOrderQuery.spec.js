import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useOrderQuery } from '@/composables/order/useOrderQuery.js'

const mocks = vi.hoisted(() => ({ listOrders: vi.fn(), showToast: vi.fn() }))
vi.mock('@/lib/api.js', () => ({
  api: { domains: { orders: { listOrders: mocks.listOrders } } },
}))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

describe('order query request ordering', () => {
  beforeEach(() => { vi.resetAllMocks() })
  afterEach(() => { vi.useRealTimers() })

  it.each(['resolve', 'reject'])('ignores a stale request that will %s after the archive result', async outcome => {
    const old = deferred()
    mocks.listOrders.mockReturnValueOnce(old.promise).mockResolvedValueOnce({
      orders: [{ id: 2 }], total: 1, pending: 0, producing: 0, completed: 1,
    })
    const query = useOrderQuery()
    const pending = query.load()
    query.archiveFilter.value = 'completed'
    await query.archiveChange()
    old[outcome](outcome === 'resolve' ? { orders: [{ id: 1 }], total: 99 } : new Error('stale'))
    await pending
    expect(query.orders.value).toEqual([{ id: 2 }])
    expect(query.total.value).toBe(1)
    expect(query.completedCount.value).toBe(1)
    expect(query.loading.value).toBe(false)
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it('keeps loading until the latest request finishes', async () => {
    const old = deferred(), latest = deferred()
    mocks.listOrders.mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
    const query = useOrderQuery()
    const first = query.load(), second = query.load()
    old.resolve({ orders: [{ id: 1 }] })
    await first
    expect(query.loading.value).toBe(true)
    latest.resolve({ orders: [{ id: 2 }] })
    await second
    expect(query.loading.value).toBe(false)
    expect(query.orders.value).toEqual([{ id: 2 }])
  })

  it.each(['searchAndLoad', 'archiveChange', 'statusChange', 'customerChange'])(
    '%s cancels the pending debounced search',
    async action => {
      vi.useFakeTimers()
      mocks.listOrders.mockResolvedValue({ orders: [] })
      const query = useOrderQuery()
      query.debouncedSearch()
      await query[action]()
      await vi.advanceTimersByTimeAsync(300)
      expect(mocks.listOrders).toHaveBeenCalledTimes(1)
    },
  )

  it('reports a current request failure and clears loading', async () => {
    mocks.listOrders.mockRejectedValue(new Error('current failure'))
    const query = useOrderQuery()
    await query.load()
    expect(mocks.showToast).toHaveBeenCalledWith('current failure', 'error')
    expect(query.loading.value).toBe(false)
  })
})
