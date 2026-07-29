import { describe, expect, it, vi } from 'vitest'

import { useTraceSearch } from '@/composables/useTraceSearch.js'


function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}


describe('useTraceSearch', () => {
  it('keeps the newest response when an older request finishes last', async () => {
    const first = deferred()
    const second = deferred()
    const traceApi = {
      trace: vi.fn()
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise),
      traceByOrder: vi.fn(),
    }
    const trace = useTraceSearch(traceApi)

    const firstSearch = trace.search({ code: 'SERIAL-OLD', mode: 'serial' })
    const secondSearch = trace.search({ code: 'SERIAL-NEW', mode: 'serial' })
    second.resolve({ item: { serial_no: 'SERIAL-NEW' } })
    await secondSearch

    expect(trace.result.value.item.serial_no).toBe('SERIAL-NEW')
    expect(trace.searching.value).toBe(false)

    first.resolve({ item: { serial_no: 'SERIAL-OLD' } })
    expect(await firstSearch).toEqual({ applied: false })
    expect(trace.result.value.item.serial_no).toBe('SERIAL-NEW')
  })

  it('ignores an obsolete error without clearing the latest result', async () => {
    const first = deferred()
    const second = deferred()
    const traceApi = {
      trace: vi.fn()
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise),
      traceByOrder: vi.fn(),
    }
    const trace = useTraceSearch(traceApi)

    const firstSearch = trace.search({ code: 'SERIAL-OLD', mode: 'serial' })
    const secondSearch = trace.search({ code: 'SERIAL-NEW', mode: 'serial' })
    second.resolve({ item: { serial_no: 'SERIAL-NEW' } })
    await secondSearch
    first.reject(new Error('obsolete failure'))

    expect(await firstSearch).toEqual({ applied: false })
    expect(trace.result.value.item.serial_no).toBe('SERIAL-NEW')
  })

  it('passes order pagination and clears only on the latest error', async () => {
    const error = new Error('查询失败')
    const traceApi = {
      trace: vi.fn(),
      traceByOrder: vi.fn().mockRejectedValue(error),
    }
    const trace = useTraceSearch(traceApi)
    trace.result.value = { order: { order_no: 'ORDER-OLD' } }

    const outcome = await trace.search({
      code: 'ORDER-NEW',
      mode: 'order',
      page: 2,
      perPage: 50,
    })

    expect(traceApi.traceByOrder).toHaveBeenCalledWith('ORDER-NEW', {
      page: 2,
      per_page: 50,
    })
    expect(outcome).toEqual({ applied: true, error })
    expect(trace.result.value).toBeNull()
    expect(trace.searching.value).toBe(false)
  })
})
