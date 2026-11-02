import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MaterialList from '@/views/MaterialList.vue'

const mocks = vi.hoisted(() => ({
  listMaterials: vi.fn(),
  listSuppliers: vi.fn(),
  getMaterialLogs: vi.fn(),
  getMaterialConsumptions: vi.fn(),
  materialStockChange: vi.fn(),
  createMaterialConsumption: vi.fn(),
  deleteMaterialConsumption: vi.fn(),
  getMaterialImpact: vi.fn(),
  deleteMaterial: vi.fn(),
  listOrders: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      materials: mocks,
      orders: { listOrders: mocks.listOrders },
    },
  },
}))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

const mounted = []
function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
async function page() {
  const wrapper = mount(MaterialList)
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}
const material = (id, quantity = 20) => ({ id, name: `物料${id}`, quantity, unit: '件' })

beforeEach(() => {
  Object.values(mocks).forEach(mock => mock.mockReset())
  mocks.listMaterials.mockResolvedValue({
    materials: [material(1), material(2, 200)], total: 2, summary: {}, material_types: [],
  })
  mocks.listSuppliers.mockResolvedValue({ suppliers: [], total: 0 })
  mocks.getMaterialLogs.mockResolvedValue({ logs: [], total: 0 })
  mocks.getMaterialConsumptions.mockResolvedValue({ consumptions: [], total: 0 })
  mocks.listOrders.mockResolvedValue({ orders: [] })
  mocks.createMaterialConsumption.mockResolvedValue({ new_quantity: 19 })
  vi.spyOn(window, 'prompt').mockReturnValue('错录撤销')
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  mounted.splice(0).forEach(wrapper => wrapper.unmount())
  vi.unstubAllGlobals()
})

describe('material consumption order selection', () => {
  it.each(['', 'ORDER-B'])('invalidates a selected order when the user types %j', async value => {
    const wrapper = await page()
    await wrapper.vm.openConsume(material(1))
    wrapper.vm.selectOrder({ id: 100, order_no: 'ORDER-A' })
    await nextTick()
    await wrapper.find('input[placeholder="搜索订单号..."]').setValue(value)
    wrapper.vm.consumeForm.quantity = 1
    await wrapper.vm.doConsume()
    expect(mocks.createMaterialConsumption).toHaveBeenCalledWith(1, expect.objectContaining({
      order_id: null, quantity: 1,
    }))
  })

  it('retains a selected order on focus and permits consumption without an order', async () => {
    const wrapper = await page()
    await wrapper.vm.openConsume(material(1))
    wrapper.vm.consumeForm.quantity = 1
    await wrapper.vm.doConsume()
    expect(mocks.createMaterialConsumption).toHaveBeenLastCalledWith(1, expect.objectContaining({ order_id: null }))
    wrapper.vm.selectOrder({ id: 100, order_no: 'ORDER-A' })
    await nextTick()
    await wrapper.find('input[placeholder="搜索订单号..."]').trigger('focus')
    wrapper.vm.consumeForm.quantity = 1
    await wrapper.vm.doConsume()
    expect(mocks.createMaterialConsumption).toHaveBeenLastCalledWith(1, expect.objectContaining({ order_id: 100 }))
  })

  it('ignores old search success, old failure and responses after selection', async () => {
    const wrapper = await page()
    await wrapper.vm.openConsume(material(1))
    const old = deferred()
    const latest = deferred()
    mocks.listOrders.mockImplementationOnce(() => old.promise).mockImplementationOnce(() => latest.promise)
    wrapper.vm.orderSearch = 'OLD'
    const oldRequest = wrapper.vm.searchOrders()
    wrapper.vm.orderSearch = 'NEW'
    const latestRequest = wrapper.vm.searchOrders()
    latest.resolve({ orders: [{ id: 2, order_no: 'NEW' }] })
    await latestRequest
    old.resolve({ orders: [{ id: 1, order_no: 'OLD' }] })
    await oldRequest
    expect(wrapper.vm.orderResults).toEqual([{ id: 2, order_no: 'NEW' }])

    const failure = deferred()
    mocks.listOrders.mockImplementationOnce(() => failure.promise)
    wrapper.vm.orderSearch = 'FAIL'
    const failingRequest = wrapper.vm.searchOrders()
    wrapper.vm.orderSearch = 'NEW'
    await wrapper.vm.searchOrders()
    wrapper.vm.selectOrder({ id: 2, order_no: 'NEW' })
    failure.reject(new Error('stale failure'))
    await failingRequest
    expect(wrapper.vm.consumeForm.order_id).toBe(2)
    expect(wrapper.vm.orderDropdown).toBe(false)

    const pending = deferred()
    mocks.listOrders.mockImplementationOnce(() => pending.promise)
    const request = wrapper.vm.searchOrders()
    wrapper.vm.selectOrder({ id: 3, order_no: 'CHOSEN' })
    pending.resolve({ orders: [{ id: 4, order_no: 'LATE' }] })
    await request
    expect(wrapper.vm.orderDropdown).toBe(false)
    expect(wrapper.vm.consumeForm.order_id).toBe(3)
  })
})

describe('material mutation response ownership', () => {
  it.each(['different material', 'same material', 'same object'])('does not close a new stock session for the %s', async scenario => {
    const wrapper = await page()
    const reply = deferred()
    mocks.materialStockChange.mockImplementationOnce(() => reply.promise)
    const firstMaterial = material(1)
    wrapper.vm.openStock(firstMaterial)
    wrapper.vm.stockForm.quantity = 4
    const request = wrapper.vm.doStock()
    wrapper.vm.showStock = false
    wrapper.vm.openStock(scenario === 'same object' ? firstMaterial : material(scenario === 'same material' ? 1 : 2, 200))
    wrapper.vm.stockForm.quantity = 8
    reply.resolve({ new_quantity: 24 })
    await request
    expect(mocks.materialStockChange).toHaveBeenCalledWith(1, { type: 'in', quantity: 4, remark: '' })
    expect(wrapper.vm.selectedMaterial.quantity).toBe(scenario === 'same object' ? 20 : 200)
    expect(wrapper.vm.showStock).toBe(true)
    expect(wrapper.vm.stockForm.quantity).toBe(8)
  })

  it('does not erase a new consume form or refresh its records after an old consumption finishes', async () => {
    const wrapper = await page()
    const reply = deferred()
    mocks.createMaterialConsumption.mockImplementationOnce(() => reply.promise)
    await wrapper.vm.openConsume(material(1))
    wrapper.vm.consumeForm.quantity = 4
    const request = wrapper.vm.doConsume()
    wrapper.vm.showConsume = false
    await wrapper.vm.openConsume(material(2, 200))
    wrapper.vm.consumeForm.quantity = 8
    wrapper.vm.consumeForm.notes = '物料2的新记录'
    const reads = mocks.getMaterialConsumptions.mock.calls.length
    reply.resolve({ new_quantity: 16 })
    await request
    expect(wrapper.vm.selectedMaterial.quantity).toBe(200)
    expect(wrapper.vm.consumeForm).toMatchObject({ quantity: 8, notes: '物料2的新记录' })
    expect(mocks.getMaterialConsumptions).toHaveBeenCalledTimes(reads)
  })

  it('does not assign a reversed balance to a newly opened material', async () => {
    const wrapper = await page()
    const reply = deferred()
    mocks.deleteMaterialConsumption.mockImplementationOnce(() => reply.promise)
    await wrapper.vm.openConsume(material(1))
    const request = wrapper.vm.undoConsume({ id: 70, quantity: 4 })
    wrapper.vm.showConsume = false
    await wrapper.vm.openConsume(material(2, 200))
    const reads = mocks.getMaterialConsumptions.mock.calls.length
    reply.resolve({ new_quantity: 24 })
    await request
    expect(wrapper.vm.selectedMaterial.quantity).toBe(200)
    expect(mocks.getMaterialConsumptions).toHaveBeenCalledTimes(reads)
  })

  it('updates the active material after stock, consumption and reversal', async () => {
    const wrapper = await page()
    mocks.materialStockChange.mockResolvedValue({ new_quantity: 24 })
    wrapper.vm.openStock(material(1))
    wrapper.vm.stockForm.quantity = 4
    await wrapper.vm.doStock()
    expect(wrapper.vm.selectedMaterial.quantity).toBe(24)
    expect(wrapper.vm.showStock).toBe(false)
    await wrapper.vm.openConsume(material(1, 24))
    wrapper.vm.consumeForm.quantity = 1
    await wrapper.vm.doConsume()
    expect(wrapper.vm.selectedMaterial.quantity).toBe(19)
    expect(wrapper.vm.consumeForm.quantity).toBe(0)
    mocks.deleteMaterialConsumption.mockResolvedValue({ new_quantity: 24 })
    await wrapper.vm.undoConsume({ id: 70 })
    expect(wrapper.vm.selectedMaterial.quantity).toBe(24)
  })
})

describe('material detail consumption history', () => {
  it('retains reversal evidence while charting only active consumption', async () => {
    const chart = vi.fn(function () { this.destroy = vi.fn() })
    vi.stubGlobal('Chart', chart)
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({})
    const wrapper = await page()
    mocks.getMaterialConsumptions.mockResolvedValue({
      consumptions: [
        { id: 1, quantity: 2, status: 'active', created_at: '2026-11-01', order_no: 'VALID' },
        { id: 2, quantity: 7, status: 'reversed', created_at: '2026-11-01', order_no: 'REVERSED', reversal_reason: '错录撤销' },
      ],
      total: 2,
    })
    await wrapper.vm.openDetail(material(1))
    await nextTick()
    wrapper.vm.renderTrendChart()
    const config = chart.mock.calls.at(-1)[1]
    expect(config.data.datasets[0].data).toEqual([2])
    expect(wrapper.text()).toContain('仅有效消耗')
    expect(wrapper.text()).toContain('REVERSED')
    expect(wrapper.text()).toContain('已撤销')
    expect(wrapper.text()).toContain('错录撤销')
  })
})

describe('material delete impact', () => {
  it.each([
    [{ refs: 1, can_delete: false, blockers: ['references'] }, '正在被 1 个地方引用'],
    [{ refs: 0, can_delete: false, inventory_quantity: 3, stock_log_count: 0, blockers: ['inventory'] }, '库存非零'],
    [{ refs: 0, can_delete: false, inventory_quantity: 0, stock_log_count: 2, blockers: ['stock_history'] }, '历史流水'],
  ])('explains a blocked delete without submitting it', async (impact, message) => {
    const wrapper = await page()
    mocks.getMaterialImpact.mockResolvedValue(impact)
    await wrapper.vm.remove(material(1))
    expect(mocks.deleteMaterial).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining(message), 'error')
  })

  it.each([{ refs: 0 }, { refs: 0, can_delete: true, blockers: [] }])('retains deletable and legacy impact behavior', async impact => {
    const wrapper = await page()
    mocks.getMaterialImpact.mockResolvedValue(impact)
    await wrapper.vm.remove(material(1))
    expect(mocks.deleteMaterial).toHaveBeenCalledWith(1)
  })
})
