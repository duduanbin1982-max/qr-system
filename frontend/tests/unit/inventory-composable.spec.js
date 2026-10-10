import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
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
  inventoryExportUrl: vi.fn(),
  inventoryExportCsvUrl: vi.fn(),
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
      inventoryExportUrl: mocks.inventoryExportUrl,
      inventoryExportCsvUrl: mocks.inventoryExportCsvUrl,
    },
    orders: { listOrders: mocks.listOrders },
  } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))

function mountHarness() {
  let state
  const harness = defineComponent({
    setup() {
      state = useInventory()
      return () => h('div')
    },
  })
  return { wrapper: mount(harness), get state() { return state } }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}


describe('inventory composable contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.inventoryTurnover.mockResolvedValue({ items: [] })
    mocks.listLocations.mockResolvedValue({ locations: [] })
    mocks.createInventory.mockResolvedValue({ id: 1 })
    mocks.updateInventory.mockResolvedValue({ message: 'updated' })
    mocks.listInventory.mockResolvedValue({ items: [] })
    mocks.inventoryStats.mockResolvedValue({})
    mocks.inventoryExportUrl.mockReturnValue('/api/inventory/export?keyword=待出库')
    mocks.inventoryExportCsvUrl.mockReturnValue('/api/inventory/export.csv?keyword=待出库')
    mocks.listOrders.mockResolvedValue({ orders: [] })
    globalThis.confirm = vi.fn(() => true)
  })

  it('reads structured turnover and location responses', async () => {
    mocks.inventoryTurnover.mockResolvedValue({ items: [{ id: 1, turnover_rate: 2 }] })
    mocks.listLocations.mockResolvedValue({
      locations: [{ location: 'A-01', item_count: 2 }, { location: 'B-02', item_count: 1 }],
    })
    const harness = mountHarness()
    await flushPromises()
    const inventory = harness.state

    await inventory.loadTurnover()
    await inventory.loadLocations()

    expect(inventory.turnoverData.value).toEqual([{ id: 1, turnover_rate: 2 }])
    expect(inventory.locations.value).toEqual(['A-01', 'B-02'])
    harness.wrapper.unmount()
  })

  it('exports the current order view to native CSV with active filters and sorting', async () => {
    const harness = mountHarness()
    const inventory = harness.state
    inventory.searchKeyword.value = '泵'
    inventory.specificationFilter.value = ['加厚', '标准']
    inventory.qualityStatusFilter.value = 'qualified'
    inventory.sortBy.value = 'quantity'
    inventory.sortDir.value = 'asc'
    inventory.selectedIds.value = [7, 9]

    inventory.exportCsv()

    expect(mocks.inventoryExportCsvUrl).toHaveBeenCalledWith({
      keyword: '泵', low_stock: '', location: '', specification: '加厚,标准',
      quality_status: 'qualified', sort_by: 'quantity', sort_dir: 'asc', inventory_id: '7,9',
    })
  })

  it('normalizes an empty order id on create and strips audited fields on edit', async () => {
    const harness = mountHarness()
    await flushPromises()
    const inventory = harness.state
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
    harness.wrapper.unmount()
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
    const harness = mountHarness()
    await flushPromises()
    const inventory = harness.state

    await inventory.doCount()
    inventory.countItems.value[0].actual_qty = 4
    await inventory.saveCountItem(inventory.countItems.value[0])
    await inventory.approveCount()

    expect(mocks.submitCount).toHaveBeenCalledWith(3, {
      task_id: 4, actual_qty: 4, remark: '',
    })
    expect(mocks.approveCountTask).toHaveBeenCalledWith(4)
    expect(inventory.countTask.value.status).toBe('posted')
    harness.wrapper.unmount()
  })

  it('inherits the current order filters when exporting', async () => {
    const harness = mountHarness()
    await flushPromises()
    const inventory = harness.state
    inventory.setFilter({ key: 'keyword', value: '待出库' })
    inventory.setFilter({ key: 'location', value: '东库' })
    inventory.setFilter({ key: 'specifications', value: ['标准'] })
    window.open = vi.fn()

    inventory.exportExcel()

    expect(mocks.inventoryExportUrl).toHaveBeenCalledWith(expect.objectContaining({
      keyword: '待出库', location: '东库', specification: '标准',
    }))
    expect(window.open).toHaveBeenCalledWith('/api/inventory/export?keyword=待出库', '_blank')
    harness.wrapper.unmount()
  })

  it('atomically keeps the newest order query when an older response arrives last', async () => {
    const harness = mountHarness()
    await flushPromises()
    const inventory = harness.state
    const oldList = deferred()
    const oldSummary = deferred()
    const newList = deferred()
    const newSummary = deferred()
    mocks.listInventory.mockImplementation(params => params.keyword === '新筛选' ? newList.promise : oldList.promise)
    mocks.inventoryStats.mockImplementation(params => params.keyword === '新筛选' ? newSummary.promise : oldSummary.promise)

    inventory.setFilter({ key: 'keyword', value: '旧筛选' })
    const oldRequest = inventory.search()
    inventory.setFilter({ key: 'keyword', value: '新筛选' })
    const newRequest = inventory.search()

    newList.resolve({ items: [{ id: 22, product_model: 'NEW-22' }], total: 1 })
    await Promise.resolve()
    expect(inventory.items.value).toEqual([])
    expect(inventory.loading.value).toBe(true)

    newSummary.resolve({ total_items: 1, total_quantity: 22, total_value: 220 })
    await newRequest
    expect(inventory.items.value).toEqual([{ id: 22, product_model: 'NEW-22' }])
    expect(inventory.total.value).toBe(1)
    expect(inventory.stats.value).toMatchObject({ total_items: 1, total_quantity: 22, total_value: 220 })

    oldList.resolve({ items: [{ id: 11, product_model: 'OLD-11' }], total: 99 })
    oldSummary.resolve({ total_items: 99, total_quantity: 999, total_value: 9990 })
    await oldRequest
    expect(inventory.items.value).toEqual([{ id: 22, product_model: 'NEW-22' }])
    expect(inventory.total.value).toBe(1)
    expect(inventory.stats.value).toMatchObject({ total_items: 1, total_quantity: 22, total_value: 220 })
    expect(inventory.loading.value).toBe(false)
    expect(mocks.showToast).not.toHaveBeenCalled()
    harness.wrapper.unmount()
  })
})
