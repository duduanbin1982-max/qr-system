import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { hasPermission } from '@/lib/permissions.js'
import MaterialList from '@/views/MaterialList.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listMaterials: vi.fn(),
  listSuppliers: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      materials: {
        listMaterials: mocks.listMaterials,
        listSuppliers: mocks.listSuppliers,
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
    mocks.listMaterials.mockResolvedValue({
      materials: [{
        id: 1,
        name: '权限物料',
        unit: '件',
        quantity: 10,
        safe_stock: 2,
      }],
    })
    mocks.listSuppliers.mockResolvedValue({
      suppliers: [{ id: 7, name: '权限供应商' }],
    })
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
})
