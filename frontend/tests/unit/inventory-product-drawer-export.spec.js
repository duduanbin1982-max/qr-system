import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ exportUrl: vi.fn(() => '/api/inventory/product-groups/1/export') }))
vi.mock('@/lib/api.js', () => ({ api: { domains: { inventory: { productGroupDetailsExportUrl: mocks.exportUrl } } } }))

import ProductInventoryDrawer from '@/components/inventory/ProductInventoryDrawer.vue'

describe('product inventory detail export', () => {
  it('renders export only with permission and opens the facade URL', async () => {
    window.open = vi.fn()
    const wrapper = mount(ProductInventoryDrawer, {
      props: { open: true, canExport: true, product: { product_id: 1, product_code: 'P-1' }, details: { inventory_items: [] } },
      attachTo: document.body,
    })
    await document.body.querySelector('.inventory-drawer footer button').click()
    expect(mocks.exportUrl).toHaveBeenCalledWith(1, { compatibility_key: '' })
    expect(window.open).toHaveBeenCalledWith('/api/inventory/product-groups/1/export', '_blank')
  })
})
