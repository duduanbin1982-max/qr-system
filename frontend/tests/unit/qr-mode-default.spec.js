import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      qrcode: { qrcodeBatch: vi.fn() },
      orders: { recordQrPrint: vi.fn() },
    },
  },
}))
vi.mock('@/lib/store.js', () => ({ showToast: vi.fn() }))

import { useQrcode } from '@/composables/useQrcode.js'


describe('QR print mode defaults', () => {
  it('defaults to serial mode for orders without a locked mode', () => {
    const qr = useQrcode()

    expect(qr.qrMode.value).toBe('serial')

    qr.openQrPrint({ id: 1, qr_mode: '' })

    expect(qr.qrMode.value).toBe('serial')
  })

  it('respects an already locked order mode', () => {
    const qr = useQrcode()

    qr.openQrPrint({ id: 2, qr_mode: 'order' })

    expect(qr.qrMode.value).toBe('order')
  })

  it('keeps serial mode for orders already printed in serial mode', () => {
    const qr = useQrcode()

    qr.openQrPrint({ id: 3, qr_mode: 'serial' })

    expect(qr.qrMode.value).toBe('serial')
  })
})
