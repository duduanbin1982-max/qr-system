import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAdminUsers } from '@/composables/settings/useAdminUsers.js'


const mocks = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getUserRoles: vi.fn(),
  setUserRoles: vi.fn(),
  updateUser: vi.fn(),
  createUser: vi.fn(),
  listRoles: vi.fn(),
  listRoleGroups: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: {
    users: {
      listUsers: mocks.listUsers,
      getUserRoles: mocks.getUserRoles,
      setUserRoles: mocks.setUserRoles,
      updateUser: mocks.updateUser,
      createUser: mocks.createUser,
    },
    roles: {
      listRoles: mocks.listRoles,
      listRoleGroups: mocks.listRoleGroups,
    },
  } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


describe('admin user role payload contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listUsers.mockResolvedValue({ users: [] })
    mocks.getUserRoles.mockResolvedValue({ roles: [{ id: 57 }] })
    mocks.setUserRoles.mockResolvedValue({ message: 'saved' })
    mocks.updateUser.mockResolvedValue({ message: 'updated' })
    mocks.createUser.mockResolvedValue({ id: 88 })
    mocks.listRoles.mockResolvedValue({ roles: [] })
    mocks.listRoleGroups.mockResolvedValue({ role_groups: [] })
  })

  it('does not copy a custom junction role into the base role field when activating an account', async () => {
    const users = useAdminUsers()
    users.openEditAdmin({
      id: 10336,
      username: '1000_perf',
      name: '杜斌',
      role: 'worker',
      role_code: 'performance_reviewer_v57',
      status: 'inactive',
      is_admin_user: false,
    })
    await users.loadUserRoles(10336)
    users.adminForm.status = 'active'

    await users.saveAdmin()

    const payload = mocks.updateUser.mock.calls[0][1]
    expect(payload.status).toBe('active')
    expect(payload).not.toHaveProperty('role')
    expect(payload).not.toHaveProperty('role_id')
    expect(mocks.setUserRoles).toHaveBeenCalledWith(10336, [57])
  })

  it('still sends an explicit base role when creating an administrator', async () => {
    const users = useAdminUsers()
    users.openAddAdmin()
    Object.assign(users.adminForm, {
      username: 'new_admin',
      name: 'New Admin',
      role: 'admin',
    })

    await users.saveAdmin()

    expect(mocks.createUser).toHaveBeenCalledWith(expect.objectContaining({ role: 'admin' }))
  })
})
