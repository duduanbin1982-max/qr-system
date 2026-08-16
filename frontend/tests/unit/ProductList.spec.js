import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProductList from '@/views/ProductList.vue'
import {
  createProductForm,
  normalizeProductPayload,
  positiveBomQuantity,
} from '@/composables/productForm.js'


const mocks = vi.hoisted(() => ({
  listProducts: vi.fn(),
  createProduct: vi.fn(),
  updateProduct: vi.fn(),
  previewProductCode: vi.fn(),
  listProductBom: vi.fn(),
  listProductAttachments: vi.fn(),
  listMaterials: vi.fn(),
  listProcesses: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      products: {
        listProducts: mocks.listProducts,
        createProduct: mocks.createProduct,
        updateProduct: mocks.updateProduct,
        previewProductCode: mocks.previewProductCode,
        listProductBom: mocks.listProductBom,
        listProductAttachments: mocks.listProductAttachments,
        deleteProduct: vi.fn(),
        restoreProduct: vi.fn(),
        purgeProduct: vi.fn(),
        uploadProductImport: vi.fn(),
        uploadProductAttachment: vi.fn(),
        deleteProductAttachment: vi.fn(),
        addProductBom: vi.fn(),
        deleteProductBom: vi.fn(),
      },
      materials: { listMaterials: mocks.listMaterials },
      processes: { listProcesses: mocks.listProcesses },
    },
  },
}))
vi.mock('@/lib/auth.js', () => ({ can: vi.fn(() => true) }))
vi.mock('@/lib/store.js', () => ({ showToast: vi.fn() }))
vi.mock('@/lib/router.js', () => ({ router: { page: 'products' } }))


describe('ProductList integrity', () => {
  beforeEach(() => {
    Object.values(mocks).forEach(mock => mock.mockReset())
    mocks.listProducts.mockResolvedValue({
      products: [{
        id: 1,
        product_name: '分页产品',
        product_code: 'P-001',
        category: '结构件',
        weight: 0,
        price: 0,
      }],
      total: 501,
      summary: { total: 501, structural: 400, machining: 101 },
    })
    mocks.createProduct.mockResolvedValue({ id: 2, product_code: 'P-002' })
    mocks.previewProductCode.mockResolvedValue({ product_code: 'P-PREVIEW' })
    mocks.listProductBom.mockResolvedValue({ bom: [] })
    mocks.listProductAttachments.mockResolvedValue({ attachments: [] })
    mocks.listMaterials.mockResolvedValue({ materials: [] })
    mocks.listProcesses.mockResolvedValue({ items: [] })
  })

  it('uses server summaries and real pagination', async () => {
    const wrapper = mount(ProductList)
    await flushPromises()

    expect(wrapper.text()).toContain('501')
    expect(wrapper.text()).toContain('400')
    expect(wrapper.text()).toContain('101')
    expect(mocks.listProducts).toHaveBeenLastCalledWith({ page: 1, limit: 20 })

    await wrapper.vm.nextPage()
    expect(mocks.listProducts).toHaveBeenLastCalledWith({ page: 2, limit: 20 })
  })

  it('normalizes blank optional numbers before create', async () => {
    const wrapper = mount(ProductList)
    await flushPromises()
    wrapper.vm.openAdd()
    wrapper.vm.form.product_name = '空数值产品'
    wrapper.vm.form.model = 'EMPTY-01'
    wrapper.vm.form.weight = ''
    wrapper.vm.form.price = ''

    await wrapper.vm.save()

    expect(mocks.createProduct).toHaveBeenCalledWith(expect.objectContaining({
      product_name: '空数值产品',
      weight: null,
      price: null,
    }))
    expect(mocks.createProduct.mock.calls[0][0]).not.toHaveProperty('product_code')
  })
})


describe('product form policy', () => {
  it('preserves explicit zero while mapping blanks to null', () => {
    expect(normalizeProductPayload(createProductForm({ weight: 0, price: 0 }))).toEqual(
      expect.objectContaining({ weight: 0, price: 0 }),
    )
    expect(normalizeProductPayload(createProductForm())).toEqual(
      expect.objectContaining({ weight: null, price: null }),
    )
  })

  it('rejects silent BOM quantity fallback', () => {
    expect(() => positiveBomQuantity('')).toThrow('单位用量必须是大于0的有效数字')
    expect(() => positiveBomQuantity(-1)).toThrow('单位用量必须是大于0的有效数字')
    expect(positiveBomQuantity('1.5')).toBe(1.5)
  })
})
