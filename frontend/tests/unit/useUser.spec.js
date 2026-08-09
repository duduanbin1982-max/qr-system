import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useUser } from '@/composables/useUser.js'


const mocks = vi.hoisted(() => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
  restoreUser: vi.fn(),
  permanentDeleteUser: vi.fn(),
  resetPassword: vi.fn(),
  unlockUser: vi.fn(),
  listPositions: vi.fn(),
  listProcesses: vi.fn(),
  showToast: vi.fn(),
  can: vi.fn(() => true),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: {
    users: {
      listUsers: mocks.listUsers,
      createUser: mocks.createUser,
      updateUser: mocks.updateUser,
      deleteUser: mocks.deleteUser,
      restoreUser: mocks.restoreUser,
      permanentDeleteUser: mocks.permanentDeleteUser,
      resetPassword: mocks.resetPassword,
      unlockUser: mocks.unlockUser,
    },
    positions: { listPositions: mocks.listPositions },
    processes: { listProcesses: mocks.listProcesses },
  } },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))
vi.mock('@/lib/auth.js', () => ({ can: mocks.can }))


describe('employee management composable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.can.mockReturnValue(true)
    mocks.listUsers.mockResolvedValue({
      users: [],
      total: 0,
      summary: { total: 0, active: 0, inactive: 0, deleted: 0 },
    })
    mocks.listPositions.mockResolvedValue({ positions: [] })
    mocks.listProcesses.mockResolvedValue({ processes: [] })
    mocks.createUser.mockResolvedValue({ id: 88, password: 'must-not-leak' })
    mocks.updateUser.mockResolvedValue({ message: 'updated' })
    mocks.restoreUser.mockResolvedValue({ message: 'restored' })
    mocks.permanentDeleteUser.mockResolvedValue({ message: 'anonymized' })
  })

  it('creates independent state per component instance', () => {
    const first = useUser()
    const second = useUser()

    expect(first.users).not.toBe(second.users)
    first.searchKeyword.value = 'first'
    expect(second.searchKeyword.value).toBe('')
  })

  it('uses server summary instead of counts from the current page', async () => {
    mocks.listUsers.mockResolvedValue({
      users: [{ id: 1, status: 'active' }],
      total: 20,
      summary: { total: 27, active: 21, inactive: 4, deleted: 2 },
    })
    const state = useUser()

    await state.load()

    expect(state.activeCount.value).toBe(21)
    expect(state.inactiveCount.value).toBe(4)
    expect(state.deletedCount.value).toBe(2)
    expect(state.totalStaff.value).toBe(25)
  })

  it('submits explicit null and empty values when clearing assignments', async () => {
    const state = useUser()
    state.openEdit({
      id: 19,
      username: 'worker19',
      name: '员工十九',
      status: 'active',
      position_id: 5,
      process_ids: '10,11',
    })
    state.form.value.position_id = ''
    state.selectedProcessIds.value = []
    state.onProcessChange()

    await state.save()

    expect(mocks.updateUser).toHaveBeenCalledWith(
      19,
      expect.objectContaining({ position_id: null, process_ids: '' }),
    )
  })

  it('requires an explicit create password and never exposes it in a toast', async () => {
    const state = useUser()
    state.openAdd()
    Object.assign(state.form.value, {
      username: 'newworker',
      name: '新员工',
      password: 'short',
    })
    await state.save()
    expect(mocks.createUser).not.toHaveBeenCalled()

    state.form.value.password = 'Worker123'
    await state.save()

    expect(mocks.createUser).toHaveBeenCalledOnce()
    expect(JSON.stringify(mocks.showToast.mock.calls)).not.toContain('must-not-leak')
  })

  it('requires a reason and passes it to identity anonymization', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('员工离职资料归档')
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const state = useUser()

    await state.purgeUser(22, '已删除员工')

    expect(mocks.permanentDeleteUser).toHaveBeenCalledWith(
      22, { reason: '员工离职资料归档' },
    )
  })

  it('validates reset passwords before sending them', async () => {
    vi.spyOn(window, 'prompt')
      .mockReturnValueOnce('weak')
      .mockReturnValueOnce('NewPass123')
    const state = useUser()

    await state.resetPwd({ id: 23 })
    expect(mocks.resetPassword).not.toHaveBeenCalled()

    await state.resetPwd({ id: 23 })
    expect(mocks.resetPassword).toHaveBeenCalledWith(
      23, { password: 'NewPass123' },
    )
  })
})
