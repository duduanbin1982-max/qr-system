import { describe, expect, it, vi } from 'vitest'

import { useOrderRework } from '@/composables/order/useOrderRework.js'


const mocks = vi.hoisted(() => ({
  report: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { scan: { report: mocks.report } } },
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


describe('useOrderRework', () => {
  it('submits rework through the report endpoint', async () => {
    mocks.report.mockResolvedValue({ message: 'report OK' })
    const load = vi.fn()
    const rework = useOrderRework({
      load,
      isCompletedOrder: () => false,
      completedReadonlyToast: vi.fn(),
    })

    rework.openRework({ id: 9, status: 'producing' })
    rework.reworkForm.value = {
      process_id: '12',
      quantity: 2,
      reason: '尺寸返修',
    }
    await rework.submitRework()

    expect(mocks.report).toHaveBeenCalledWith({
      order_id: 9,
      process_id: 12,
      quantity: 2,
      report_type: 'rework',
      remark: '尺寸返修',
    })
    expect(load).toHaveBeenCalled()
  })
})
