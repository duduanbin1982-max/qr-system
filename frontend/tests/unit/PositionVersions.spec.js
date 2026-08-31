import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usePositionVersions } from '@/composables/settings/usePositionVersions.js'
import { positionVersionsApi } from '@/lib/api/position-versions.js'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  can: vi.fn((permission) => mocks.permissions.has(permission)),
  auth: { user: { id: 2000 } },
  createPosition: vi.fn(),
  listPositionVersions: vi.fn(),
  getPositionVersion: vi.fn(),
  getPositionVersionImpact: vi.fn(),
  createPositionRevision: vi.fn(),
  updatePositionVersion: vi.fn(),
  submitPositionVersion: vi.fn(),
  approvePositionVersion: vi.fn(),
  rejectPositionVersion: vi.fn(),
  cancelPositionVersion: vi.fn(),
  listPositionLifecycleRequests: vi.fn(),
  requestPositionRetirement: vi.fn(),
  requestPositionReactivation: vi.fn(),
  approvePositionLifecycle: vi.fn(),
  rejectPositionLifecycle: vi.fn(),
  request: vi.fn(),
}))

vi.mock('@/lib/auth.js', () => ({ auth: mocks.auth, can: mocks.can }))
vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      positions: { createPosition: mocks.createPosition },
      positionVersions: mocks,
    },
  },
}))
vi.mock('@/lib/api/client.js', () => ({ request: mocks.request }))

const root = {
  id: 7,
  position_code: 'POS-0007',
  lifecycle_status: 'active',
  current_effective_version_id: 71,
  row_version: 4,
}

function version(overrides = {}) {
  return {
    id: 71,
    position_id: 7,
    version: 1,
    name: '车工',
    description: '机加工岗位',
    process_ids: [11],
    processes: [{ process_id: 11, seq_order: 1 }],
    status: 'published',
    row_version: 2,
    created_by: 1000,
    created_by_name: '制单人',
    revision_reason: '历史基线',
    ...overrides,
  }
}

function detail(versions) {
  return { position: { ...root }, versions, events: [] }
}

describe('usePositionVersions', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((value) => {
      if (typeof value?.mockReset === 'function') value.mockReset()
    })
    mocks.permissions = new Set([
      'positions:create',
      'positions:submit',
      'positions:approve',
      'positions:reject',
      'positions:history',
      'positions:impact',
      'positions:retire',
      'positions:reactivate',
    ])
    mocks.auth.user = { id: 2000 }
    mocks.listPositionLifecycleRequests.mockResolvedValue([])
    mocks.getPositionVersionImpact.mockResolvedValue({
      impact: { total_references: 2, references: [] },
    })
  })

  it('exposes current pending history and impact state from version responses', async () => {
    const published = version()
    const pending = version({
      id: 72,
      version: 2,
      status: 'pending_approval',
      supersedes_version_id: 71,
    })
    const history = version({ id: 70, version: 0, status: 'superseded' })
    mocks.listPositionVersions.mockResolvedValue(detail([published, pending, history]))

    const state = usePositionVersions()
    await state.loadPosition(7)

    expect(state.current.value.id).toBe(71)
    expect(state.pending.value.id).toBe(72)
    expect(state.history.value.map((item) => item.id)).toEqual([70])
    await state.setActiveTab('impact')
    expect(mocks.getPositionVersionImpact).toHaveBeenCalledWith(71)
    expect(state.impact.value.total_references).toBe(2)
  })

  it('blocks self approval before the API call', async () => {
    const state = usePositionVersions({ actor: { id: 1000 } })
    state.selectedVersion.value = version({
      id: 72,
      status: 'pending_approval',
      created_by: 1000,
    })

    await state.approveSelected()

    expect(mocks.approvePositionVersion).not.toHaveBeenCalled()
    expect(state.operationError.value).toContain('必须不同')
  })

  it('blocks duplicate commands while preserving root concurrency data', async () => {
    const draft = version({ id: 72, version: 2, status: 'draft', row_version: 5 })
    const submitted = { ...draft, status: 'pending_approval', row_version: 6 }
    let finish
    mocks.submitPositionVersion.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    mocks.listPositionVersions.mockResolvedValue(detail([submitted]))
    const state = usePositionVersions()
    state.selectedVersion.value = draft

    const first = state.submitSelected()
    const duplicate = state.submitSelected()

    await expect(duplicate).resolves.toBeNull()
    expect(mocks.submitPositionVersion).toHaveBeenCalledOnce()
    expect(mocks.submitPositionVersion).toHaveBeenCalledWith(72, {
      row_version: 5,
      idempotency_key: expect.stringMatching(/^position-submit:/),
    })
    finish(submitted)
    await first
    expect(state.commandBusy.value).toBe(false)
  })

  it('uses root row_version and immutable command keys for revisions', async () => {
    const published = version()
    const draft = version({ id: 72, version: 2, status: 'draft', row_version: 0 })
    mocks.createPositionRevision.mockResolvedValue(draft)
    mocks.listPositionVersions.mockResolvedValue(detail([published, draft]))
    const state = usePositionVersions()
    state.root.value = { ...root }

    await state.createRevision({
      name: '车工',
      description: '调整岗位',
      process_ids: [11, 12],
      revision_reason: '调整工序范围',
    })

    expect(mocks.createPositionRevision).toHaveBeenCalledWith(7, expect.objectContaining({
      row_version: 4,
      process_ids: [11, 12],
      revision_reason: '调整工序范围',
      idempotency_key: expect.stringMatching(/^position-revision:/),
    }))
  })
})

describe('position version API routes', () => {
  beforeEach(() => {
    mocks.request.mockReset()
    mocks.request.mockResolvedValue({})
  })

  it('uses only versioned revision and lifecycle endpoints', async () => {
    const payload = { row_version: 3, idempotency_key: 'position-command-1' }
    await positionVersionsApi.listPositionVersions(7)
    await positionVersionsApi.getPositionVersion(71)
    await positionVersionsApi.getPositionVersionImpact(71)
    await positionVersionsApi.createPositionRevision(7, payload)
    await positionVersionsApi.updatePositionVersion(72, payload)
    await positionVersionsApi.submitPositionVersion(72, payload)
    await positionVersionsApi.approvePositionVersion(72, payload)
    await positionVersionsApi.rejectPositionVersion(72, payload)
    await positionVersionsApi.cancelPositionVersion(72, payload)
    await positionVersionsApi.listPositionLifecycleRequests(7)
    await positionVersionsApi.requestPositionRetirement(7, payload)
    await positionVersionsApi.requestPositionReactivation(7, payload)
    await positionVersionsApi.approvePositionLifecycle(90, payload)
    await positionVersionsApi.rejectPositionLifecycle(90, payload)

    expect(mocks.request.mock.calls).toEqual([
      ['GET', '/api/positions/7/versions'],
      ['GET', '/api/position-versions/71'],
      ['GET', '/api/position-versions/71/impact'],
      ['POST', '/api/positions/7/revisions', payload],
      ['PUT', '/api/position-versions/72', payload],
      ['POST', '/api/position-versions/72/submit', payload],
      ['POST', '/api/position-versions/72/approve', payload],
      ['POST', '/api/position-versions/72/reject', payload],
      ['POST', '/api/position-versions/72/cancel', payload],
      ['GET', '/api/positions/7/lifecycle-requests'],
      ['POST', '/api/positions/7/retirement-requests', payload],
      ['POST', '/api/positions/7/reactivation-requests', payload],
      ['POST', '/api/position-lifecycle-requests/90/approve', payload],
      ['POST', '/api/position-lifecycle-requests/90/reject', payload],
    ])
  })
})
