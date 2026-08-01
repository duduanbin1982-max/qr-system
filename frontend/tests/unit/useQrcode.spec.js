import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useQrcode } from '@/composables/useQrcode.js'


const mocks = vi.hoisted(() => ({
  qrcodeBatch: vi.fn(),
  recordQrPrint: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      qrcode: { qrcodeBatch: mocks.qrcodeBatch },
      orders: { recordQrPrint: mocks.recordQrPrint },
    },
  },
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


describe('useQrcode print status', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="modal"><div id="qr-print-root"></div></div>'
    vi.spyOn(window, 'print').mockImplementation(() => {})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(HTMLImageElement.prototype, 'complete', 'get').mockReturnValue(true)
    mocks.recordQrPrint.mockResolvedValue({
      print_status: {
        qr_print_count: 1,
        qr_printed_at: '2026-07-30 08:00:00',
        qr_printed_by_name: '管理员',
      },
    })
  })

  it('records the first print and updates the order marker', async () => {
    const qr = useQrcode()
    const order = { id: 9, order_no: 'ORD-009', qr_print_count: 0 }
    qr.openQrPrint(order)
    qr.qrCodes.value = [{ order_no: 'ORD-009', qrcode: 'data:image/png;base64,AA==' }]

    qr.printQrCodes()
    await flushPromises()

    expect(window.print).toHaveBeenCalledOnce()
    expect(mocks.recordQrPrint).toHaveBeenCalledWith(9, {
      mode: 'order',
      copies: 1,
      label_count: 1,
    })
    expect(order.qr_print_count).toBe(1)
    expect(qr.qrPrintTitle(order)).toContain('管理员')
  })

  it('warns when opening an order that was already printed', () => {
    const qr = useQrcode()

    qr.openQrPrint({ id: 9, order_no: 'ORD-009', qr_print_count: 2 })

    expect(mocks.showToast).toHaveBeenCalledWith(
      '该订单二维码已打印 2 次，本次属于重新打印',
      'warn',
    )
  })

  it('does not reprint when the operator cancels confirmation', () => {
    const qr = useQrcode()
    vi.mocked(window.confirm).mockReturnValue(false)
    qr.openQrPrint({ id: 9, order_no: 'ORD-009', qr_print_count: 1 })
    qr.qrCodes.value = [{ order_no: 'ORD-009', qrcode: 'data:image/png;base64,AA==' }]

    qr.printQrCodes()

    expect(window.print).not.toHaveBeenCalled()
    expect(mocks.recordQrPrint).not.toHaveBeenCalled()
  })
})
