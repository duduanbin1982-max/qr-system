import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  normalizePositionProcessIds,
  usePositions,
} from '@/composables/settings/usePositions.js'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  can: vi.fn(permission => mocks.permissions.has(permission)),
  listPositions: vi.fn(),
  listProcesses: vi.fn(),
  createPosition: vi.fn(),
  updatePosition: vi.fn(),
  deletePosition: vi.fn(),
  getPositionImpact: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/auth.js', () => ({ can: mocks.can }))
vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      positions: {
        listPositions: mocks.listPositions,
        createPosition: mocks.createPosition,
        updatePosition: mocks.updatePosition,
        deletePosition: mocks.deletePosition,
        getPositionImpact: mocks.getPositionImpact,
      },
      processes: { listProcesses: mocks.listProcesses },
    },
  },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


describe('position management P0 contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.permissions = new Set([
      'positions:view',
      'positions:create',
      'positions:edit',
      'positions:delete',
    ])
    mocks.listPositions.mockResolvedValue({ positions: [] })
    mocks.listProcesses.mockResolvedValue({ processes: [] })
    mocks.createPosition.mockResolvedValue({ id: 8 })
    mocks.updatePosition.mockResolvedValue({ message: 'updated' })
    mocks.deletePosition.mockResolvedValue({ message: 'deleted' })
    mocks.getPositionImpact.mockResolvedValue({ users: 0 })
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('normalizes process_ids and the real structured processes response', () => {
    expect(normalizePositionProcessIds({ process_ids: [11, '12', 11] })).toEqual([11, 12])
    expect(normalizePositionProcessIds({
      processes: [{ process_id: 21 }, { process_id: '22' }],
    })).toEqual([21, 22])
  })

  it('preserves process assignments when editing fields from a real list response', async () => {
    const positions = usePositions({ autoLoad: false })
    positions.openEditPosition({
      id: 3,
      name: '焊工',
      description: '原描述',
      status: 'active',
      processes: [{ process_id: 11, process_name: '焊接' }],
    })
    positions.positionForm.description = '新描述'

    await positions.savePosition()

    expect(mocks.updatePosition).toHaveBeenCalledWith(3, {
      name: '焊工',
      description: '新描述',
      status: 'active',
      process_ids: [11],
    })
  })

  it('fails closed when delete impact lookup fails', async () => {
    const positions = usePositions({ autoLoad: false })
    mocks.getPositionImpact.mockRejectedValue(new Error('影响查询失败'))

    await positions.deletePosition(3)

    expect(mocks.deletePosition).not.toHaveBeenCalled()
    expect(confirm).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('影响查询失败', 'error')
  })

  it('fails closed when deactivation impact lookup fails', async () => {
    const positions = usePositions({ autoLoad: false })
    positions.openEditPosition({
      id: 3,
      name: '焊工',
      description: '',
      status: 'active',
      process_ids: [11],
    })
    positions.positionForm.status = 'inactive'
    mocks.getPositionImpact.mockRejectedValue(new Error('影响查询失败'))

    await positions.savePosition()

    expect(mocks.updatePosition).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('影响查询失败', 'error')
  })

  it('guards create edit and delete commands without permission', async () => {
    mocks.permissions = new Set(['positions:view'])
    const positions = usePositions({ autoLoad: false })

    positions.openAddPosition()
    positions.openEditPosition({ id: 3, name: '焊工' })
    await positions.deletePosition(3)

    expect(positions.showPositionModal.value).toBe(false)
    expect(mocks.getPositionImpact).not.toHaveBeenCalled()
    expect(mocks.deletePosition).not.toHaveBeenCalled()
  })
})
