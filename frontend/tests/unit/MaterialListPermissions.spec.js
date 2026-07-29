import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { hasPermission } from '@/lib/permissions.js'
import MaterialList from '@/views/MaterialList.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listMaterials: vi.fn(),
  listSuppliers: vi.fn(),
  getMaterialLogs: vi.fn(),
  getMaterialConsumptions: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      materials: {
        listMaterials: mocks.listMaterials,
        listSuppliers: mocks.listSuppliers,
        getMaterialLogs: mocks.getMaterialLogs,
        getMaterialConsumptions: mocks.getMaterialConsumptions,
      },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  can: vi.fn(permission => mocks.permissions.has(permission)),
}))

vi.mock('@/lib/store.js', () => ({ showToast: vi.fn() }))


describe('MaterialList permissions', () => {
  beforeEach(() => {
    mocks.permissions = new Set([
      'materials:view',
      'materials:stock',
      'suppliers:view',
      'suppliers:delete',
    ])
    mocks.listMaterials.mockReset()
    mocks.listSuppliers.mockReset()
    mocks.getMaterialLogs.mockReset()
    mocks.getMaterialConsumptions.mockReset()
    mocks.listMaterials.mockResolvedValue({
      materials: [{
        id: 1,
        name: '权限物料',
        unit: '件',
        quantity: 10,
        safe_stock: 2,
        abc_class: 'A',
      }],
      total: 1,
      summary: { total: 1, low_stock: 0, inventory_value: 20 },
      material_types: [],
    })
    mocks.listSuppliers.mockResolvedValue({
      suppliers: [{ id: 7, name: '权限供应商' }],
      total: 1,
    })
    mocks.getMaterialLogs.mockResolvedValue({ logs: [], total: 0 })
    mocks.getMaterialConsumptions.mockResolvedValue({ consumptions: [], total: 0 })
  })

  it('shows only the operations granted to the current role', async () => {
    const wrapper = mount(MaterialList)
    await flushPromises()

    expect(wrapper.text()).toContain('出入库')
    expect(wrapper.text()).not.toContain('消耗')
    expect(wrapper.text()).not.toContain('编辑')
    expect(wrapper.text()).not.toContain('新增物料')

    const supplierButton = wrapper.findAll('button').find(button => button.text().includes('供应商管理'))
    expect(supplierButton).toBeTruthy()
    await supplierButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('权限供应商')
    expect(wrapper.findAll('button').some(button => button.text() === '删除')).toBe(true)
    expect(wrapper.findAll('button').some(button => button.text().includes('新增供应商'))).toBe(false)
  })

  it('keeps legacy material manage permission compatible in the frontend', () => {
    const user = { permissions: ['materials:manage'] }
    const operations = [
      'materials:create',
      'materials:edit',
      'materials:delete',
      'materials:stock',
      'materials:consume',
      'suppliers:view',
      'suppliers:create',
      'suppliers:edit',
      'suppliers:delete',
    ]

    expect(operations.every(permission => hasPermission(user, permission))).toBe(true)
  })

  it('uses server summaries and resets pagination for material searches', async () => {
    mocks.listMaterials.mockResolvedValue({
      materials: [{ id: 21, name: '分页物料', quantity: 2, safe_stock: 3, abc_class: 'B' }],
      total: 25,
      summary: { total: 125, low_stock: 8, inventory_value: 4567.8 },
      material_types: ['钢材', '铝材'],
    })
    const wrapper = mount(MaterialList)
    await flushPromises()

    expect(wrapper.text()).toContain('125')
    expect(wrapper.text()).toContain('4567.80')
    expect(mocks.listMaterials).toHaveBeenLastCalledWith({ page: 1, limit: 20 })

    await wrapper.vm.nextPage()
    await flushPromises()
    expect(mocks.listMaterials).toHaveBeenLastCalledWith({ page: 2, limit: 20 })

    wrapper.vm.searchText = '紧固件'
    await wrapper.vm.searchAndLoad()
    expect(mocks.listMaterials).toHaveBeenLastCalledWith({
      page: 1,
      limit: 20,
      keyword: '紧固件',
    })

    wrapper.vm.materialTypeFilter = '钢材'
    await wrapper.vm.filterAndLoad()
    expect(mocks.listMaterials).toHaveBeenLastCalledWith({
      page: 1,
      limit: 20,
      keyword: '紧固件',
      material_type: '钢材',
    })
  })

  it('ignores superseded list responses', async () => {
    let resolveFirst
    let resolveSecond
    mocks.listMaterials
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
    const wrapper = mount(MaterialList)

    wrapper.vm.searchText = '新条件'
    const latestRequest = wrapper.vm.searchAndLoad()
    resolveSecond({
      materials: [{ id: 2, name: '新结果', abc_class: 'A' }],
      total: 1,
      summary: { total: 1, low_stock: 0, inventory_value: 1 },
      material_types: [],
    })
    await latestRequest
    expect(wrapper.vm.materials).toEqual([expect.objectContaining({ name: '新结果' })])

    resolveFirst({
      materials: [{ id: 1, name: '旧结果', abc_class: 'C' }],
      total: 1,
      summary: { total: 1, low_stock: 1, inventory_value: 0 },
      material_types: [],
    })
    await flushPromises()
    expect(wrapper.vm.materials).toEqual([expect.objectContaining({ name: '新结果' })])
  })

  it('creates fresh state when the page is mounted again', async () => {
    const firstWrapper = mount(MaterialList)
    await flushPromises()
    firstWrapper.vm.searchText = '旧搜索'
    firstWrapper.vm.page = 3
    firstWrapper.unmount()

    const secondWrapper = mount(MaterialList)
    await flushPromises()
    expect(secondWrapper.vm.searchText).toBe('')
    expect(secondWrapper.vm.page).toBe(1)
    expect(mocks.listMaterials).toHaveBeenLastCalledWith({ page: 1, limit: 20 })
  })

  it('paginates supplier management and inventory activity independently', async () => {
    mocks.listSuppliers.mockImplementation(params => {
      if (params.limit === 500) {
        return Promise.resolve({
          suppliers: Array.from({ length: 25 }, (_, index) => ({
            id: index + 1,
            name: `供应商 ${index + 1}`,
          })),
          total: 25,
        })
      }
      return Promise.resolve({ suppliers: [{ id: 1, name: '供应商 1' }], total: 25 })
    })
    mocks.getMaterialLogs.mockResolvedValue({ logs: [{ id: 1, type: 'in', quantity: 1 }], total: 25 })
    mocks.getMaterialConsumptions.mockResolvedValue({ consumptions: [{ id: 1, quantity: 1 }], total: 25 })
    const wrapper = mount(MaterialList)
    await flushPromises()

    await wrapper.vm.nextSupplierPage()
    expect(mocks.listSuppliers).toHaveBeenLastCalledWith({ page: 2, limit: 20 })
    wrapper.vm.supplierSearchText = '华东'
    await wrapper.vm.searchSuppliers()
    expect(mocks.listSuppliers).toHaveBeenLastCalledWith({
      page: 1,
      limit: 20,
      keyword: '华东',
    })

    const material = { id: 9, name: '活动物料' }
    await wrapper.vm.viewLogs(material)
    await wrapper.vm.nextLogsPage()
    expect(mocks.getMaterialLogs).toHaveBeenLastCalledWith(9, { page: 2, limit: 20 })

    await wrapper.vm.openConsume(material)
    await wrapper.vm.nextConsumptionsPage()
    expect(mocks.getMaterialConsumptions).toHaveBeenLastCalledWith(9, { page: 2, limit: 20 })
  })
})
