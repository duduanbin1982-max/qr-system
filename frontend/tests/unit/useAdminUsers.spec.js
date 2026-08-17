import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAdminUsers } from '@/composables/settings/useAdminUsers.js'


const mocks = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getUserRoles: vi.fn(),
  setUserRoles: vi.fn(),
  updateUser: vi.fn(),
  createUser: vi.fn(),
  permanentDeleteUser: vi.fn(),
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
      permanentDeleteUser: mocks.permanentDeleteUser,
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
    mocks.permanentDeleteUser.mockResolvedValue({ message: 'anonymized' })
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

  it('passes an explicit reason when anonymizing a deleted administrator', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('管理员账号离职归档')
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const users = useAdminUsers()

    await users.permanentDeleteAdminUser(10336)

    expect(mocks.permanentDeleteUser).toHaveBeenCalledWith(
      10336, { reason: '管理员账号离职归档' },
    )
  })

  it('separates system administrators, service accounts, and ordinary workers', () => {
    const users = useAdminUsers()
    users.allUsers.value = [
      {
        id: 1,
        username: 'root-admin',
        role: 'admin',
        role_code: 'admin',
        is_admin_user: true,
        roles: [{ id: 1, code: 'admin', name: '系统管理员' }],
      },
      {
        id: 2,
        username: '1000_perf',
        role: 'worker',
        role_code: 'performance_reviewer_v57',
        is_admin_user: false,
        roles: [{ id: 57, code: 'performance_reviewer_v57', name: '绩效主管复核' }],
      },
      {
        id: 3,
        username: 'ordinary-worker',
        role: 'worker',
        role_code: 'worker',
        is_admin_user: false,
        roles: [{ id: 2, code: 'worker', name: '普通员工' }],
      },
    ]

    expect(users.systemAdminList.value.map(user => user.id)).toEqual([1])
    expect(users.serviceAccountList.value.map(user => user.id)).toEqual([2])
    expect(users.filteredAdminList.value.map(user => user.id)).toEqual([1])

    users.setAccountMode('service')
    expect(users.filteredAdminList.value.map(user => user.id)).toEqual([2])
  })

  it('clears selection on mode changes and never selects system administrators', () => {
    const users = useAdminUsers()
    users.allUsers.value = [
      { id: 1, role_code: 'admin', is_admin_user: true, status: 'active' },
      {
        id: 2,
        role_code: 'performance_reviewer_v57',
        is_admin_user: false,
        status: 'active',
      },
      {
        id: 3,
        role_code: 'performance_plan_manager_v57',
        is_admin_user: false,
        status: 'deleted',
      },
    ]

    users.toggleSelectAllAdmins()
    expect(users.selectedAdmins.value).toEqual([])

    users.setAccountMode('service')
    users.toggleSelectAllAdmins()
    expect(users.selectedAdmins.value).toEqual([2])
    expect(users.isAllSelected.value).toBe(true)

    users.setAccountMode('admin')
    expect(users.selectedAdmins.value).toEqual([])
  })

  it('shows assigned role names and deduplicated effective permission counts', () => {
    const users = useAdminUsers()
    users.allRoles.value = [
      { id: 57, code: 'reviewer', permissions: '["performance:view_all","performance:review_department"]' },
      { id: 58, code: 'exporter', permissions: ['performance:view_all', 'performance:export'] },
    ]
    const serviceAccount = {
      roles: [
        { id: 57, code: 'reviewer', name: '绩效复核人' },
        { id: 58, code: 'exporter', name: '绩效导出人' },
      ],
    }

    expect(users.userRoleNames(serviceAccount)).toEqual(['绩效复核人', '绩效导出人'])
    expect(users.userPermissionSummary(serviceAccount)).toBe('3 项权限')

    users.allRoles.value.push({ id: 1, code: 'admin', permissions: '["*"]' })
    expect(users.userPermissionSummary({ roles: [{ id: 1, code: 'admin' }] })).toBe('全部权限')
  })
})
