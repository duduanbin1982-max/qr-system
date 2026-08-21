import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  normalizePositionProcessIds,
  usePositions,
} from '@/composables/settings/usePositions.js'
import Positions from '@/views/settings/Positions.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  can: vi.fn(permission => mocks.permissions.has(permission)),
  listPositions: vi.fn(),
  listProcesses: vi.fn(),
  createPosition: vi.fn(),
  updatePosition: vi.fn(),
  deletePosition: vi.fn(),
  getPositionImpact: vi.fn(),
  listPositionVersions: vi.fn(),
  getPositionVersionImpact: vi.fn(),
  listPositionLifecycleRequests: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/auth.js', () => ({ auth: { user: { id: 2000 } }, can: mocks.can }))
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
      positionVersions: {
        listPositionVersions: mocks.listPositionVersions,
        getPositionVersionImpact: mocks.getPositionVersionImpact,
        listPositionLifecycleRequests: mocks.listPositionLifecycleRequests,
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
    mocks.listPositionLifecycleRequests.mockResolvedValue([])
    mocks.getPositionVersionImpact.mockResolvedValue({ impact: { total_references: 0, references: [] } })
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

  it('shows stable list data and current pending history and impact views', async () => {
    mocks.permissions.add('positions:history')
    mocks.permissions.add('positions:impact')
    mocks.permissions.add('positions:submit')
    mocks.permissions.add('positions:approve')
    mocks.permissions.add('positions:reject')
    const published = {
      id: 71,
      position_id: 7,
      version: 1,
      name: '车工',
      description: '机加工岗位',
      process_ids: [11],
      status: 'published',
      row_version: 2,
    }
    const pending = {
      ...published,
      id: 72,
      version: 2,
      status: 'pending_approval',
      supersedes_version_id: 71,
      created_by: 1000,
    }
    const history = { ...published, id: 70, version: 0, status: 'superseded' }
    mocks.listPositions.mockResolvedValue({
      positions: [{
        id: 7,
        position_code: 'POS-0007',
        name: '车工',
        description: '机加工岗位',
        lifecycle_status: 'active',
        current_effective_version_id: 71,
        current_version: published,
        open_version: pending,
        employee_count: 27,
        processes: [{ process_id: 11, process_name: '精车' }],
      }],
      total: 1,
    })
    mocks.listProcesses.mockResolvedValue({ processes: [{ id: 11, process_name: '精车' }] })
    mocks.listPositionVersions.mockResolvedValue({
      position: {
        id: 7,
        position_code: 'POS-0007',
        name: '车工',
        lifecycle_status: 'active',
        current_effective_version_id: 71,
        row_version: 4,
      },
      versions: [published, pending, history],
      events: [],
    })

    const wrapper = mount(Positions)
    await flushPromises()

    expect(wrapper.text()).toContain('POS-0007')
    expect(wrapper.text()).toContain('27')
    await wrapper.get('.name-link').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-tab="current"]').exists()).toBe(true)
    expect(wrapper.get('[data-tab="pending"]').exists()).toBe(true)
    expect(wrapper.get('[data-tab="history"]').exists()).toBe(true)
    expect(wrapper.get('[data-tab="impact"]').exists()).toBe(true)
    expect(wrapper.get('.version-editor input').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-tab="pending"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('待审批')
    await wrapper.get('[data-tab="impact"]').trigger('click')
    await flushPromises()
    expect(mocks.getPositionVersionImpact).toHaveBeenCalled()
  })
})
