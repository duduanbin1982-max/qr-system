import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useRoleGroups } from '@/composables/settings/useRoleGroups.js'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  can: vi.fn((permission) => mocks.permissions.has(permission)),
  listRoleGroups: vi.fn(),
  listRoles: vi.fn(),
  createRoleGroup: vi.fn(),
  updateRoleGroup: vi.fn(),
  deleteRoleGroup: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/auth.js', () => ({ can: mocks.can }))
vi.mock('@/lib/api.js', () => ({
  api: { domains: { roles: {
    listRoleGroups: mocks.listRoleGroups,
    listRoles: mocks.listRoles,
    createRoleGroup: mocks.createRoleGroup,
    updateRoleGroup: mocks.updateRoleGroup,
    deleteRoleGroup: mocks.deleteRoleGroup,
  } } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


describe('role group permission UI contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.permissions = new Set(['role_groups:view', 'role_groups:create', 'role_groups:edit'])
    mocks.listRoleGroups.mockResolvedValue({ role_groups: [] })
    mocks.listRoles.mockResolvedValue({ roles: [] })
    mocks.createRoleGroup.mockResolvedValue({ id: 90 })
    mocks.updateRoleGroup.mockResolvedValue({ message: 'updated' })
    mocks.deleteRoleGroup.mockResolvedValue({ message: 'deleted' })
  })

  it('guards create and edit actions and never sends legacy permissions', async () => {
    const groups = useRoleGroups()

    expect(groups.canCreate.value).toBe(true)
    expect(groups.canEdit.value).toBe(true)
    expect(groups.canDelete.value).toBe(false)

    groups.openAddGroup()
    Object.assign(groups.groupForm, {
      name: '生产组',
      description: '生产人员',
      status: 'active',
    })
    await groups.saveGroup()

    expect(mocks.createRoleGroup).toHaveBeenCalledWith({
      name: '生产组',
      description: '生产人员',
      parent_id: null,
      status: 'active',
    })
    expect(mocks.createRoleGroup.mock.calls[0][0]).not.toHaveProperty('permissions')
  })

  it('does not open or invoke destructive actions without permission', async () => {
    mocks.permissions = new Set(['role_groups:view'])
    const groups = useRoleGroups()

    groups.openAddGroup()
    expect(groups.showGroupModal.value).toBe(false)
    expect(mocks.showToast).toHaveBeenCalledWith('无权新增角色组', 'error')

    await groups.deleteGroup(1)
    expect(mocks.deleteRoleGroup).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('无权删除角色组', 'error')
  })
})
