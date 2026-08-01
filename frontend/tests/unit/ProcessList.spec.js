import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ProcessList from '@/views/ProcessList.vue'


const mocks = vi.hoisted(() => ({
  listProcesses: vi.fn(),
  showToast: vi.fn(),
  router: { page: 'all-processes' },
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { processes: { listProcesses: mocks.listProcesses } } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))
vi.mock('@/lib/auth.js', () => ({ can: vi.fn(() => true) }))
vi.mock('@/lib/router.js', () => ({ router: mocks.router }))


describe('ProcessList loading', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.listProcesses.mockReset()
    mocks.showToast.mockReset()
    mocks.router.page = 'all-processes'
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('retries the initial request and only reports an error after all attempts fail', async () => {
    mocks.listProcesses
      .mockRejectedValueOnce(new Error('temporary one'))
      .mockRejectedValueOnce(new Error('temporary two'))
      .mockResolvedValueOnce({
        processes: [{
          id: 1,
          process_name: '喷漆',
          category: '结构件',
          status: 'active',
          seq_order: 1,
        }],
        total: 1,
        category_counts: { '结构件': 1, '机加工': 0 },
      })

    const wrapper = mount(ProcessList)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(mocks.listProcesses).toHaveBeenCalledTimes(3)
    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('喷漆')
    expect(wrapper.text()).toContain('工序总数')
  })
})
