import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const inventory = vi.hoisted(() => ({
  allocationPreview: vi.fn(),
  productGroupOutbound: vi.fn(),
  listAllocationRuns: vi.fn(),
  reverseAllocation: vi.fn(),
}))
vi.mock('@/lib/api.js', () => ({ api: { domains: { inventory } } }))

import ProductInventoryDrawer from '@/components/inventory/ProductInventoryDrawer.vue'

const details = {
  compatibility_groups: [
    { compatibility_key: 'standard', specification: '标准', available_quantity: 8 },
    { compatibility_key: 'thick', specification: '加厚', available_quantity: 5 },
  ],
  inventory_items: [
    { inventory_id: 10, order_no: 'ORDER-10', compatibility_key: 'standard', available_quantity: 8 },
    { inventory_id: 20, order_no: 'ORDER-20', compatibility_key: 'thick', available_quantity: 5 },
  ],
}
const preview = {
  compatibility_key: 'standard', preview_digest: 'validated-preview-digest',
  available_quantity: 8, allocated_quantity: 1,
  items: [{ sequence_no: 1, inventory_id: 10, order_no: 'ORDER-10', allocated_quantity: 1 }],
}
let wrapper

function mountDrawer(props = {}) {
  wrapper = mount(ProductInventoryDrawer, {
    props: {
      open: true, product: { product_id: 1, product_code: 'PRODUCT-1' }, details,
      capabilities: { allocation_preview_enabled: true, cross_order_outbound_enabled: true },
      ...props,
    },
    global: { stubs: { teleport: true } },
  })
  return wrapper
}

async function createPreview() {
  await wrapper.find('.allocation-actions button').trigger('click')
  await flushPromises()
}

async function openHistory() {
  mountDrawer({ product: null })
  await wrapper.setProps({ product: { product_id: 1, product_code: 'PRODUCT-1' } })
  await flushPromises()
}

beforeEach(() => {
  vi.resetAllMocks()
  inventory.allocationPreview.mockResolvedValue(preview)
  inventory.productGroupOutbound.mockResolvedValue({ id: 7 })
  inventory.listAllocationRuns.mockResolvedValue({ items: [] })
  inventory.reverseAllocation.mockResolvedValue({ id: 8 })
  vi.spyOn(window, 'alert').mockImplementation(() => {})
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})
afterEach(() => wrapper?.unmount())

describe('product inventory drawer allocation behavior', () => {
  it('renders a read-only FIFO preview and prevents a second request while pending', async () => {
    let resolve
    inventory.allocationPreview.mockReturnValue(new Promise(done => { resolve = done }))
    mountDrawer()
    await wrapper.find('.allocation-actions button').trigger('click')
    expect(wrapper.find('.allocation-actions button').element.disabled).toBe(true)
    expect(wrapper.find('.allocation-actions button').text()).toBe('计算中…')
    wrapper.find('.allocation-actions button').element.click()
    await flushPromises()
    expect(inventory.allocationPreview).toHaveBeenCalledExactlyOnceWith(1, {
      quantity: 1, mode: 'fifo', compatibility_key: '', selected_inventory_ids: [], reason: '',
    })
    expect(inventory.productGroupOutbound).not.toHaveBeenCalled()
    resolve(preview)
    await flushPromises()
    expect(wrapper.find('.allocation-actions button').element.disabled).toBe(false)
    expect(wrapper.find('.allocation-result').text()).toContain('validated-preview-digest')
    expect(wrapper.find('.allocation-result').text()).toContain('ORDER-10')
  })

  it('filters manual sources and passes the selected quantities and reason to the facade', async () => {
    mountDrawer()
    const selects = wrapper.findAll('.allocation-form select')
    await selects[0].setValue('thick')
    await selects[1].setValue('manual')
    await wrapper.find('input[type="number"]').setValue('3')
    await wrapper.find('.reason-field input').setValue('发货')
    expect(wrapper.findAll('.source-list label')).toHaveLength(1)
    expect(wrapper.find('.source-list').text()).toContain('ORDER-20')
    await wrapper.find('.source-list input').setValue(true)
    await createPreview()
    expect(inventory.allocationPreview).toHaveBeenCalledExactlyOnceWith(1, {
      quantity: 3, mode: 'manual', compatibility_key: 'thick', selected_inventory_ids: [20], reason: '发货',
    })
  })

  it('submits the server preview digest and resolved compatibility key, then refreshes history', async () => {
    mountDrawer()
    await createPreview()
    inventory.listAllocationRuns.mockResolvedValue({ items: [{ id: 7, mode: 'fifo', requested_quantity: 1 }] })
    await wrapper.findAll('.allocation-actions button')[1].trigger('click')
    await flushPromises()
    expect(inventory.productGroupOutbound).toHaveBeenCalledExactlyOnceWith(1, {
      quantity: 1, mode: 'fifo', compatibility_key: 'standard', selected_inventory_ids: [],
      preview_digest: 'validated-preview-digest', idempotency_key: expect.stringMatching(/^inventory-ui-\d+$/), reason: '',
    })
    expect(inventory.listAllocationRuns).toHaveBeenCalledExactlyOnceWith({ product_id: 1, limit: 20 })
    expect(wrapper.find('.allocation-result').exists()).toBe(false)
    expect(wrapper.find('.history-row').text()).toContain('#7')
    expect(window.alert).toHaveBeenCalledExactlyOnceWith('出库成功')
  })

  it('keeps the preview and reports a rejected outbound without a success notification', async () => {
    inventory.productGroupOutbound.mockRejectedValue(new Error('预览已过期'))
    mountDrawer()
    await createPreview()
    await wrapper.findAll('.allocation-actions button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.allocation-error').text()).toBe('预览已过期')
    expect(wrapper.find('.allocation-result').exists()).toBe(true)
    expect(wrapper.find('.allocation-actions button').element.disabled).toBe(false)
    expect(inventory.listAllocationRuns).not.toHaveBeenCalled()
    expect(window.alert).not.toHaveBeenCalled()
  })

  it.each([
    [new Error('库存不足'), '库存不足'],
    [{}, '无法生成分配预览'],
  ])('retains the preview error contract for %s', async (error, message) => {
    inventory.allocationPreview.mockRejectedValue(error)
    mountDrawer()
    await createPreview()
    expect(wrapper.find('.allocation-error').text()).toBe(message)
    expect(wrapper.find('.allocation-actions button').element.disabled).toBe(false)
    expect(wrapper.find('.allocation-result').exists()).toBe(false)
  })

  it('hides allocation actions when their feature flags are disabled', async () => {
    mountDrawer({ capabilities: {} })
    expect(wrapper.find('.allocation-form').exists()).toBe(false)
    await wrapper.setProps({ product: { product_id: 2 } })
    await flushPromises()
    expect(inventory.listAllocationRuns).not.toHaveBeenCalled()
    await wrapper.setProps({ capabilities: { allocation_preview_enabled: true } })
    await createPreview()
    expect(wrapper.findAll('.allocation-actions button')).toHaveLength(1)
    expect(inventory.productGroupOutbound).not.toHaveBeenCalled()
  })

  it('resets product-specific selections and preview when the product changes', async () => {
    mountDrawer()
    await wrapper.findAll('.allocation-form select')[0].setValue('thick')
    await wrapper.findAll('.allocation-form select')[1].setValue('manual')
    await wrapper.find('.source-list input').setValue(true)
    await createPreview()
    await wrapper.setProps({ product: { product_id: 2, product_code: 'PRODUCT-2' } })
    await flushPromises()
    expect(wrapper.find('h3').text()).toBe('PRODUCT-2')
    expect(wrapper.find('.allocation-form select').element.value).toBe('')
    expect(wrapper.findAll('.source-list input').every(input => !input.element.checked)).toBe(true)
    expect(wrapper.find('.allocation-result').exists()).toBe(false)
    expect(inventory.listAllocationRuns).toHaveBeenCalledExactlyOnceWith({ product_id: 2, limit: 20 })
    await createPreview()
    expect(inventory.allocationPreview).toHaveBeenLastCalledWith(2, expect.objectContaining({
      compatibility_key: '', selected_inventory_ids: [],
    }))
  })

  it('treats a failed history query as empty history and releases the loading state', async () => {
    inventory.listAllocationRuns.mockRejectedValue(new Error('查询失败'))
    await openHistory()
    expect(wrapper.text()).toContain('暂无正式分配记录')
    expect(wrapper.text()).not.toContain('加载中…')
    expect(window.alert).not.toHaveBeenCalled()
  })

  it.each([false, true])('requires confirmation before reversal (confirmed: %s)', async confirmed => {
    inventory.listAllocationRuns.mockResolvedValueOnce({ items: [{ id: 7, mode: 'fifo', requested_quantity: 1 }] })
    await openHistory()
    window.confirm.mockReturnValue(confirmed)
    await wrapper.find('.history-row button').trigger('click')
    await flushPromises()
    expect(window.confirm).toHaveBeenCalledExactlyOnceWith('确认撤销分配运行 #7？')
    if (confirmed) {
      expect(inventory.reverseAllocation).toHaveBeenCalledExactlyOnceWith(7, {
        idempotency_key: expect.stringMatching(/^inventory-ui-reverse-7-\d+$/), reason: '库存产品视图撤销',
      })
      expect(inventory.listAllocationRuns).toHaveBeenCalledTimes(2)
      expect(window.alert).toHaveBeenCalledExactlyOnceWith('撤销成功')
    } else {
      expect(inventory.reverseAllocation).not.toHaveBeenCalled()
      expect(inventory.listAllocationRuns).toHaveBeenCalledTimes(1)
      expect(window.alert).not.toHaveBeenCalled()
    }
  })

  it('shows a reversal failure and leaves the original history visible', async () => {
    inventory.listAllocationRuns.mockResolvedValue({ items: [{ id: 7, mode: 'fifo', requested_quantity: 1 }] })
    inventory.reverseAllocation.mockRejectedValue(new Error('撤销被拒绝'))
    await openHistory()
    await wrapper.find('.history-row button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.allocation-error').text()).toBe('撤销被拒绝')
    expect(wrapper.find('.history-row').text()).toContain('#7')
    expect(inventory.listAllocationRuns).toHaveBeenCalledTimes(1)
    expect(window.alert).not.toHaveBeenCalled()
  })
})
