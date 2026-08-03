import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useInventory } from '@/composables/useInventory.js'


const mocks = vi.hoisted(() => ({
  inventoryTurnover: vi.fn(),
  listLocations: vi.fn(),
  createInventory: vi.fn(),
  updateInventory: vi.fn(),
  countStatus: vi.fn(),
  createCountTask: vi.fn(),
  submitCount: vi.fn(),
  approveCountTask: vi.fn(),
  listInventory: vi.fn(),
  inventoryStats: vi.fn(),
  listOrders: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: {
    inventory: {
      inventoryTurnover: mocks.inventoryTurnover,
      listLocations: mocks.listLocations,
      createInventory: mocks.createInventory,
      updateInventory: mocks.updateInventory,
      countStatus: mocks.countStatus,
      createCountTask: mocks.createCountTask,
      submitCount: mocks.submitCount,
      approveCountTask: mocks.approveCountTask,
      listInventory: mocks.listInventory,
      inventoryStats: mocks.inventoryStats,
    },
    orders: { listOrders: mocks.listOrders },
  } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))


describe('inventory composable contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.inventoryTurnover.mockResolvedValue({ items: [] })
    mocks.listLocations.mockResolvedValue({ locations: [] })
    mocks.createInventory.mockResolvedValue({ id: 1 })
    mocks.updateInventory.mockResolvedValue({ message: 'updated' })
    mocks.listInventory.mockResolvedValue({ items: [] })
    mocks.inventoryStats.mockResolvedValue({})
    mocks.listOrders.mockResolvedValue({ orders: [] })
    globalThis.confirm = vi.fn(() => true)
  })

  it('reads structured turnover and location responses', async () => {
    mocks.inventoryTurnover.mockResolvedValue({ items: [{ id: 1, turnover_rate: 2 }] })
    mocks.listLocations.mockResolvedValue({
      locations: [{ location: 'A-01', item_count: 2 }, { location: 'B-02', item_count: 1 }],
    })
    const inventory = useInventory()

    await inventory.loadTurnover()
    await inventory.loadLocations()

    expect(inventory.turnoverData.value).toEqual([{ id: 1, turnover_rate: 2 }])
    expect(inventory.locations.value).toEqual(['A-01', 'B-02'])
  })

  it('normalizes an empty order id on create and strips audited fields on edit', async () => {
    const inventory = useInventory()
    inventory.openAdd()
    Object.assign(inventory.form.value, { product_model: 'MODEL-1', quantity: 3, order_id: '' })
    await inventory.save()

    expect(mocks.createInventory).toHaveBeenCalledWith(expect.objectContaining({
      product_model: 'MODEL-1', quantity: 3, order_id: null,
    }))

    inventory.openEdit({ id: 7, product_model: 'MODEL-1', quantity: 3, order_id: 9 })
    await inventory.save()
    const updatePayload = mocks.updateInventory.mock.calls[0][1]
    expect(updatePayload).not.toHaveProperty('quantity')
    expect(updatePayload).not.toHaveProperty('order_id')
  })

  it('opens, records, and approves a persistent count task', async () => {
    const counting = {
      task: { id: 4, task_no: 'CT-4', status: 'counting' },
      items: [{ id: 8, inventory_id: 3, book_quantity: 5, actual_quantity: null, status: 'pending' }],
    }
    const submitted = {
      task: { ...counting.task, status: 'submitted' },
      items: [{ ...counting.items[0], actual_quantity: 4, difference: -1, status: 'counted' }],
    }
    mocks.countStatus.mockResolvedValueOnce({ task: null, items: [] }).mockResolvedValueOnce(submitted)
    mocks.createCountTask.mockResolvedValue(counting)
    mocks.submitCount.mockResolvedValue({ ok: true })
    mocks.approveCountTask.mockResolvedValue({
      task: { ...counting.task, status: 'posted' }, items: [],
    })
    const inventory = useInventory()

    await inventory.doCount()
    inventory.countItems.value[0].actual_qty = 4
    await inventory.saveCountItem(inventory.countItems.value[0])
    await inventory.approveCount()

    expect(mocks.submitCount).toHaveBeenCalledWith(3, {
      task_id: 4, actual_qty: 4, remark: '',
    })
    expect(mocks.approveCountTask).toHaveBeenCalledWith(4)
    expect(inventory.countTask.value.status).toBe('posted')
  })
})
