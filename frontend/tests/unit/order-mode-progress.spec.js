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
})
