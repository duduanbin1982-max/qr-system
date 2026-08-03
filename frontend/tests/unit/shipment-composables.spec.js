import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useDeliveryNote } from '@/composables/shipment/useDeliveryNote.js'
import { useShipmentActions } from '@/composables/shipment/useShipmentActions.js'
import { useShipmentEditor } from '@/composables/shipment/useShipmentEditor.js'
import { useShipmentQuery } from '@/composables/shipment/useShipmentQuery.js'


const mocks = vi.hoisted(() => ({
  listShipments: vi.fn(),
  listInventory: vi.fn(),
  draftShipment: vi.fn(),
  createShipment: vi.fn(),
  updateShipment: vi.fn(),
  deleteShipment: vi.fn(),
  shipmentImpact: vi.fn(),
  getShipment: vi.fn(),
  receiveShipment: vi.fn(),
  recordPayment: vi.fn(),
  refundPayment: vi.fn(),
  reversePayment: vi.fn(),
  cancelShipment: vi.fn(),
  updateLogistics: vi.fn(),
  completeShipment: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      shipments: {
        listShipments: mocks.listShipments,
        draftShipment: mocks.draftShipment,
        createShipment: mocks.createShipment,
        updateShipment: mocks.updateShipment,
        deleteShipment: mocks.deleteShipment,
        shipmentImpact: mocks.shipmentImpact,
        getShipment: mocks.getShipment,
        receiveShipment: mocks.receiveShipment,
        recordPayment: mocks.recordPayment,
        refundPayment: mocks.refundPayment,
        reversePayment: mocks.reversePayment,
        cancelShipment: mocks.cancelShipment,
        updateLogistics: mocks.updateLogistics,
        completeShipment: mocks.completeShipment,
      },
      inventory: { listInventory: mocks.listInventory },
    },
  },
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


describe('shipment composables', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listShipments.mockResolvedValue({
      shipments: [], total: 0, pending_count: 0, completed_count: 0,
    })
    mocks.listInventory.mockResolvedValue({ items: [] })
    mocks.draftShipment.mockResolvedValue({ shipment_no: 'OUT-20260802-001' })
    mocks.createShipment.mockResolvedValue({ message: 'created' })
    mocks.updateShipment.mockResolvedValue({ message: 'updated' })
    mocks.receiveShipment.mockResolvedValue({ message: 'received' })
    mocks.recordPayment.mockResolvedValue({ message: 'paid' })
    mocks.refundPayment.mockResolvedValue({ message: 'refunded' })
    mocks.reversePayment.mockResolvedValue({ message: 'reversed' })
    mocks.cancelShipment.mockResolvedValue({ message: 'cancelled', status: 'cancelled' })
    mocks.updateLogistics.mockResolvedValue({ message: 'updated' })
    mocks.completeShipment.mockResolvedValue({ message: 'completed' })
    globalThis.confirm = vi.fn(() => true)
  })

  it('loads filtered shipments and derives receivable totals', async () => {
    mocks.listShipments.mockResolvedValue({
      shipments: [
        { id: 1, receivable_amount: 120, paid_amount: 20 },
        { id: 2, receivable_amount: 80, paid_amount: 80 },
      ],
      total: 2,
      pending_count: 1,
      completed_count: 1,
      receivable_total: 200,
      paid_total: 100,
      unpaid_total: 100,
    })
    const query = useShipmentQuery()
    query.filterStatus.value = 'completed'
    query.searchKeyword.value = '  Acme  '

    await query.load()

    expect(mocks.listShipments).toHaveBeenCalledWith({
      page: 1, limit: 20, status: 'completed', keyword: 'Acme',
    })
    expect(query.shipments.value).toHaveLength(2)
    expect(query.receivableTotal.value).toBe(200)
    expect(query.paidTotal.value).toBe(100)
    expect(query.unpaidTotal.value).toBe(100)
    expect(query.pendingCount.value).toBe(1)
    expect(query.completedCount.value).toBe(1)
    expect(query.loading.value).toBe(false)
  })

  it('pages only when a boundary allows it and reports load errors', async () => {
    mocks.listShipments
      .mockResolvedValueOnce({ shipments: [], total: 40 })
      .mockRejectedValueOnce(new Error('network down'))
    const query = useShipmentQuery()

    await query.load()
    await query.nextPage()
    await query.prevPage()

    expect(query.page.value).toBe(1)
    expect(mocks.listShipments).toHaveBeenCalledTimes(3)
    expect(mocks.showToast).toHaveBeenCalledWith('network down', 'error')
    expect(query.loading.value).toBe(false)
  })

  it('exports the current search filters in the download URL', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const query = useShipmentQuery()
    query.filterStatus.value = 'pending'
    query.searchKeyword.value = 'Acme & Sons'

    query.exportExcel()

    expect(open).toHaveBeenCalledWith(
      '/api/shipments/export?keyword=Acme+%26+Sons&status=pending',
      '_blank',
    )
    open.mockRestore()
  })

  it('creates a shipment from a selected inventory item and quantity', async () => {
    const reload = vi.fn().mockResolvedValue(undefined)
    mocks.listInventory.mockResolvedValue({
      items: [{ id: 7, product_model: 'MODEL-7', product_name: 'Widget', unit: '件', price: 12 }],
    })
    const editor = useShipmentEditor({ reload })

    await editor.loadInventory()
    await editor.openAdd()
    editor.addItem()
    editor.selectInventory(0, editor.inventory.value[0])
    editor.updateItemQuantity(0, '3')
    editor.form.value.customer = 'Acme'
    editor.form.value.receivable_amount = 36
    await editor.save()

    expect(mocks.createShipment).toHaveBeenCalledWith(expect.objectContaining({
      shipment_no: 'OUT-20260802-001',
      customer: 'Acme',
      items: [expect.objectContaining({ inventory_id: 7, quantity: 3 })],
    }))
    expect(editor.showModal.value).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('blocks an empty shipment without calling the create endpoint', async () => {
    const editor = useShipmentEditor({ reload: vi.fn() })
    editor.showModal.value = true

    await editor.save()

    expect(mocks.createShipment).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('请添加出库产品', 'error')
  })

  it('updates an existing shipment without sending item editing fields', async () => {
    const reload = vi.fn().mockResolvedValue(undefined)
    const editor = useShipmentEditor({ reload })
    editor.openEdit({
      id: 9,
      shipment_no: 'OUT-009',
      customer: 'Old Customer',
      status: 'pending',
      receivable_amount: 50,
    })
    editor.form.value.customer = 'New Customer'

    await editor.save()

    expect(mocks.updateShipment).toHaveBeenCalledWith(9, expect.objectContaining({
      customer: 'New Customer',
    }))
    expect(mocks.updateShipment.mock.calls[0][1]).not.toHaveProperty('status')
    expect(mocks.updateShipment.mock.calls[0][1]).not.toHaveProperty('items')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('records payment and reloads after opening the remaining balance', async () => {
    const reload = vi.fn().mockResolvedValue(undefined)
    const actions = useShipmentActions({ reload })
    actions.openPayment({ id: 12, shipment_no: 'OUT-012', receivable_amount: 100, paid_amount: 40 })
    actions.payMethod.value = 'bank'
    actions.payRemark.value = 'final payment'

    await actions.doPayment()

    expect(actions.payAmount.value).toBe(60)
    expect(mocks.recordPayment).toHaveBeenCalledWith(12, expect.objectContaining({
      amount: 60, method: 'bank', remark: 'final payment',
      payment_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      idempotency_key: expect.stringContaining('receipt:12:'),
    }))
    expect(actions.showPayModal.value).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('completes a shipment only after confirmation and reloads its list', async () => {
    const reload = vi.fn().mockResolvedValue(undefined)
    const actions = useShipmentActions({ reload })

    await actions.doComplete({ id: 13, shipment_no: 'OUT-013' })

    expect(globalThis.confirm).toHaveBeenCalledWith(expect.stringContaining('OUT-013'))
    expect(mocks.completeShipment).toHaveBeenCalledWith(13)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('prints escaped delivery details and quantities', () => {
    const printDocument = { write: vi.fn(), close: vi.fn() }
    const open = vi.spyOn(window, 'open').mockReturnValue({ document: printDocument })
    const deliveryNote = useDeliveryNote()

    deliveryNote.printDeliveryNote({
      shipment_no: 'OUT-014',
      customer: '<Acme>',
      items: [{ product_model: 'M-1', product_name: 'Widget', quantity: 2, unit: '件' }],
    })

    const html = printDocument.write.mock.calls[0][0]
    expect(html).toContain('&lt;Acme&gt;')
    expect(html).toContain('<td>2</td>')
    expect(html).toContain('合计</td><td>2</td>')
    expect(printDocument.close).toHaveBeenCalledTimes(1)
    open.mockRestore()
  })
})
