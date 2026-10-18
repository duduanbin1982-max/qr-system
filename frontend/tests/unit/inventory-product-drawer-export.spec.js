import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ exportUrl: vi.fn(() => '/api/inventory/product-groups/1/export') }))
vi.mock('@/lib/api.js', () => ({ api: { domains: { inventory: { productGroupDetailsExportUrl: mocks.exportUrl } } } }))

import ProductInventoryDrawer from '@/components/inventory/ProductInventoryDrawer.vue'

let wrapper
beforeEach(() => {
  vi.spyOn(window, 'open').mockImplementation(() => null)
})
afterEach(() => wrapper?.unmount())

function mountDrawer(props = {}) {
  wrapper = mount(ProductInventoryDrawer, {
    props: {
      open: true, canExport: true,
      product: { product_id: 1, product_code: 'P-1' },
      details: { inventory_items: [], compatibility_groups: [{ compatibility_key: 'thick', specification: '加厚' }] },
      ...props,
    },
    global: { stubs: { teleport: true } },
  })
  return wrapper
}

describe('product inventory detail export', () => {
  it('renders export only with permission and opens the facade URL', async () => {
    mountDrawer()
    await wrapper.find('footer button').trigger('click')
    expect(mocks.exportUrl).toHaveBeenCalledWith(1, { compatibility_key: '' })
    expect(window.open).toHaveBeenCalledWith('/api/inventory/product-groups/1/export', '_blank')
  })

  it('passes the selected compatibility group to the export facade', async () => {
    mountDrawer({ capabilities: { allocation_preview_enabled: true } })
    await wrapper.find('.allocation-form select').setValue('thick')
    await wrapper.find('footer button').trigger('click')
    expect(mocks.exportUrl).toHaveBeenCalledExactlyOnceWith(1, { compatibility_key: 'thick' })
  })

  it('removes export access when permission is revoked', async () => {
    mountDrawer()
    await wrapper.setProps({ canExport: false })
    expect(wrapper.find('footer').text()).not.toContain('导出详情')
    expect(mocks.exportUrl).not.toHaveBeenCalled()
    expect(window.open).not.toHaveBeenCalled()
  })

  it('does not export without a product identity', async () => {
    mountDrawer({ product: null })
    await wrapper.find('footer button').trigger('click')
    expect(mocks.exportUrl).not.toHaveBeenCalled()
    expect(window.open).not.toHaveBeenCalled()
  })
})
