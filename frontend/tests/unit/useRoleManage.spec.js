import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useRoleManage } from '@/composables/settings/useRoleManage.js'


const mocks = vi.hoisted(() => ({
  listRoles: vi.fn(),
  listRoleGroups: vi.fn(),
  getPermissions: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { roles: {
    listRoles: mocks.listRoles,
    listRoleGroups: mocks.listRoleGroups,
    getPermissions: mocks.getPermissions,
    createRole: mocks.createRole,
    updateRole: mocks.updateRole,
    deleteRole: mocks.deleteRole,
  } } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

function mountHarness() {
  let state
  const harness = defineComponent({
    setup() {
      state = useRoleManage()
      return () => h('div')
    },
  })
  return { wrapper: mount(harness), get state() { return state } }
}


describe('role management security contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listRoles.mockResolvedValue({ roles: [] })
    mocks.listRoleGroups.mockResolvedValue({ role_groups: [] })
    mocks.getPermissions.mockResolvedValue({
      codes: ['page:settings', 'roles:view', 'roles:edit'],
      mergedTree: [],
    })
    mocks.createRole.mockResolvedValue({ id: 90 })
    mocks.updateRole.mockResolvedValue({ message: 'updated' })
    mocks.deleteRole.mockResolvedValue({ message: 'deleted' })
  })

  it('keeps the built-in administrator wildcard immutable when saving', async () => {
    const harness = mountHarness()
    await flushPromises()
    const roles = harness.state
    roles.permissionCodes.value = ['page:settings', 'roles:view', 'roles:edit']
    roles.openEditRole({
      id: 1,
      name: '系统管理员',
      code: 'admin',
      description: '',
      group_id: null,
      parent_id: null,
      level: 1,
      permissions: '["*"]',
      status: 'active',
      is_builtin: 1,
    })

    expect(roles.isBuiltinAdmin.value).toBe(true)
    expect(roles.wildcardSelected.value).toBe(true)
    expect(roles.selectedPerms.value).toEqual(['page:settings', 'roles:view', 'roles:edit'])

    await roles.saveRole()

    expect(mocks.updateRole).toHaveBeenCalledWith(1, expect.objectContaining({
      code: 'admin',
      status: 'active',
      permissions: '["*"]',
    }))
    harness.wrapper.unmount()
  })

  it('normalizes and deduplicates custom role permissions without a wildcard', async () => {
    const harness = mountHarness()
    await flushPromises()
    const roles = harness.state
    roles.openAddRole()
    Object.assign(roles.roleForm, { name: '生产排程员', code: 'scheduler' })
    roles.selectedPerms.value = ['roles:view', 'roles:view', 'page:settings']

    await roles.saveRole()

    expect(mocks.createRole).toHaveBeenCalledWith(expect.objectContaining({
      name: '生产排程员',
      code: 'scheduler',
      permissions: '["roles:view","page:settings","page:settings.role-manage"]',
    }))
    expect(mocks.createRole.mock.calls[0][0]).not.toHaveProperty('is_builtin')
    harness.wrapper.unmount()
  })
})
