import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getWorkpieceProgress: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { orders: { getWorkpieceProgress: mocks.getWorkpieceProgress } } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

import { useOrderProgress } from '@/composables/order/useOrderProgress.js'


describe('order progress dialog data source', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses order_process_stats for order-mode orders without workpieces', async () => {
    mocks.getWorkpieceProgress.mockResolvedValue({
      analysis: { tracking_mode: 'order' },
      quantity: 20,
      summary: {
        total_workpieces: 0,
        total_processes: 2,
        completed_processes: 1,
        order_progress_pct: 50,
        process_stats: [
          { process_id: 1, process_name: '下料', completed: 0, total: 0 },
          { process_id: 2, process_name: '打磨', completed: 0, total: 0 },
        ],
      },
      order_process_stats: [
        { process_id: 1, process_name: '下料', completed: 20, total: 20, completion_pct: 100 },
        { process_id: 2, process_name: '打磨', completed: 0, total: 20, completion_pct: 0 },
      ],
      progress: [],
      processes: [
        { process_id: 1, name: '下料', seq_order: 1 },
        { process_id: 2, name: '打磨', seq_order: 2 },
      ],
    })

    const progress = useOrderProgress()
    await progress.openProgress({ id: 515, order_no: '26093005' })

    expect(progress.isOrderTracking.value).toBe(true)
    expect(progress.progressBars.value.map(stat => stat.process_name)).toEqual(['下料', '打磨'])
    expect(progress.barPercent(progress.progressBars.value[0])).toBe(100)
    expect(progress.barPercent(progress.progressBars.value[1])).toBe(0)
  })

  it('keeps workpiece-derived process stats for serial-mode orders', async () => {
    mocks.getWorkpieceProgress.mockResolvedValue({
      analysis: { tracking_mode: 'serial' },
      summary: {
        process_stats: [
          { process_id: 1, process_name: '下料', completed: 1, total: 2 },
        ],
      },
      order_process_stats: [
        { process_id: 1, process_name: '下料', completed: 2, total: 2 },
      ],
      progress: [{ serial_no: 'S1' }],
    })

    const progress = useOrderProgress()
    await progress.openProgress({ id: 1 })

    expect(progress.isOrderTracking.value).toBe(false)
    expect(progress.progressBars.value[0].completed).toBe(1)
  })

  it('never divides by zero when process totals are empty', async () => {
    mocks.getWorkpieceProgress.mockResolvedValue({
      analysis: { tracking_mode: 'order' },
      summary: {
        process_stats: [
          { process_id: 1, process_name: '下料', completed: 0, total: 0 },
        ],
      },
      order_process_stats: [],
      progress: [],
    })

    const progress = useOrderProgress()
    await progress.openProgress({ id: 2 })

    expect(progress.barPercent({ completed: 0, total: 0 })).toBe(0)
    expect(progress.barPercent(progress.progressBars.value[0])).toBe(0)
  })

  it('keeps the newer request loading when an older request finishes first', async () => {
    let resolveFirst
    let resolveSecond
    mocks.getWorkpieceProgress
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))

    const progress = useOrderProgress()
    const firstRequest = progress.openProgress({ id: 1, order_no: 'A' })
    const secondRequest = progress.openProgress({ id: 2, order_no: 'B' })

    resolveFirst({ summary: { process_stats: [{ process_id: 'first' }] } })
    await firstRequest
    expect(progress.progressOrder.value.order_no).toBe('B')
    expect(progress.progressData.value).toBe(null)
    expect(progress.progressLoading.value).toBe(true)

    resolveSecond({ summary: { process_stats: [{ process_id: 'second' }] } })
    await secondRequest
    expect(progress.progressOrder.value.order_no).toBe('B')
    expect(progress.progressData.value.summary.process_stats[0].process_id).toBe('second')
    expect(progress.progressLoading.value).toBe(false)
  })

  it('keeps the newer order data when the older response arrives last', async () => {
    let resolveFirst
    let resolveSecond
    mocks.getWorkpieceProgress
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))

    const progress = useOrderProgress()
    const firstRequest = progress.openProgress({ id: 1, order_no: 'A' })
    const secondRequest = progress.openProgress({ id: 2, order_no: 'B' })

    resolveSecond({ summary: { process_stats: [{ process_id: 'second' }] } })
    await secondRequest
    resolveFirst({ summary: { process_stats: [{ process_id: 'first' }] } })
    await firstRequest

    expect(progress.progressOrder.value.order_no).toBe('B')
    expect(progress.progressData.value.summary.process_stats[0].process_id).toBe('second')
    expect(progress.progressLoading.value).toBe(false)
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it('ignores a stale failure after a newer request succeeds', async () => {
    let rejectFirst
    let resolveSecond
    mocks.getWorkpieceProgress
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectFirst = reject }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))

    const progress = useOrderProgress()
    const firstRequest = progress.openProgress({ id: 1, order_no: 'A' })
    const secondRequest = progress.openProgress({ id: 2, order_no: 'B' })

    resolveSecond({ summary: { process_stats: [{ process_id: 'second' }] } })
    await secondRequest
    rejectFirst(new Error('late failure'))
    await firstRequest

    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(progress.progressOrder.value.order_no).toBe('B')
    expect(progress.progressData.value.summary.process_stats[0].process_id).toBe('second')
    expect(progress.progressLoading.value).toBe(false)
  })

  it('invalidates an in-flight request when the dialog is closed', async () => {
    let resolveRequest
    mocks.getWorkpieceProgress.mockImplementationOnce(
      () => new Promise(resolve => { resolveRequest = resolve }),
    )

    const progress = useOrderProgress()
    const request = progress.openProgress({ id: 1, order_no: 'A' })
    progress.closeProgress()

    resolveRequest({ summary: { process_stats: [{ process_id: 'stale' }] } })
    await request

    expect(progress.progressOrder.value).toBe(null)
    expect(progress.progressData.value).toBe(null)
    expect(progress.progressLoading.value).toBe(false)
  })

  it('does not show a stale failure after the dialog is closed', async () => {
    let rejectRequest
    mocks.getWorkpieceProgress.mockImplementationOnce(
      () => new Promise((_resolve, reject) => { rejectRequest = reject }),
    )

    const progress = useOrderProgress()
    const request = progress.openProgress({ id: 1, order_no: 'A' })
    progress.closeProgress()

    rejectRequest(new Error('late failure'))
    await request

    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(progress.progressOrder.value).toBe(null)
    expect(progress.progressData.value).toBe(null)
    expect(progress.progressLoading.value).toBe(false)
  })

  it('shows the current request failure and closes the dialog', async () => {
    mocks.getWorkpieceProgress.mockRejectedValueOnce(new Error('current failure'))

    const progress = useOrderProgress()
    await progress.openProgress({ id: 1, order_no: 'A' })

    expect(mocks.showToast).toHaveBeenCalledTimes(1)
    expect(mocks.showToast).toHaveBeenCalledWith('加载进度失败: current failure', 'error')
    expect(progress.progressOrder.value).toBe(null)
    expect(progress.progressData.value).toBe(null)
    expect(progress.progressLoading.value).toBe(false)
  })
})
