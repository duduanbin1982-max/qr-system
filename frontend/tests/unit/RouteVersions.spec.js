import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RouteVersionEditor from '@/components/master-data/RouteVersionEditor.vue'
import { useRouteVersions } from '@/composables/useRouteVersions.js'
import { processRouteVersionsApi } from '@/lib/api/process-route-versions.js'


const mocks = vi.hoisted(() => ({
  createVersionedRoute: vi.fn(),
  listRouteVersions: vi.fn(),
  getRouteVersion: vi.fn(),
  createRouteRevision: vi.fn(),
  updateRouteVersion: vi.fn(),
  submitRouteVersion: vi.fn(),
  approveRouteVersion: vi.fn(),
  rejectRouteVersion: vi.fn(),
  getRouteVersionImpact: vi.fn(),
  requestRouteRetirement: vi.fn(),
  requestRouteReactivation: vi.fn(),
  approveRouteRetirement: vi.fn(),
  approveRouteReactivation: vi.fn(),
  listRoutePriceVersions: vi.fn(),
  request: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      processRouteVersions: mocks,
      wages: { listRoutePriceVersions: mocks.listRoutePriceVersions },
    },
  },
}))
vi.mock('@/lib/api/client.js', () => ({ request: mocks.request }))

const root = {
  id: 8,
  route_code: 'ROUTE-0008',
  lifecycle_status: 'active',
  current_effective_version_id: 81,
  row_version: 5,
}

const item = {
  id: 801,
  process_id: 7,
  process_version_id: 71,
  process_code_snapshot: 'PROC-0007',
  process_name_snapshot: '精车',
  process_category: '机加工',
  process_version: 3,
  process_version_status: 'published',
  seq_order: 10,
  is_required: 1,
  required_audit: 1,
}

function version(overrides = {}) {
  return {
    id: 81,
    process_route_id: 8,
    version: 1,
    name: '标准机加工路线',
    category: '机加工',
    description: '稳定路线',
    status: 'published',
    row_version: 2,
    revision_reason: '历史基线',
    items: [item],
    ...overrides,
  }
}

describe('useRouteVersions', () => {
  beforeEach(() => {
    Object.values(mocks).forEach(mock => mock.mockReset())
    mocks.getRouteVersionImpact.mockResolvedValue({
      impact: { total_references: 2, references: [] },
    })
    mocks.listRoutePriceVersions.mockResolvedValue({ versions: [] })
  })

  it('loads current, open and historical route versions with exact price coverage', async () => {
    const draft = version({
      id: 82,
      version: 2,
      status: 'draft',
      row_version: 0,
      supersedes_version_id: 81,
    })
    mocks.listRouteVersions.mockResolvedValue({ route: root, versions: [version(), draft], events: [] })
    mocks.listRoutePriceVersions.mockResolvedValue({
      versions: [{
        id: 91,
        route_version_id: 82,
        process_version_id: 71,
        process_id: 7,
        status: 'draft',
      }],
    })

    const state = useRouteVersions()
    await state.loadRoute(8)

    expect(state.currentVersion.value.id).toBe(81)
    expect(state.openVersion.value.id).toBe(82)
    expect(state.selectedVersion.value.id).toBe(82)
    expect(state.coverageRows.value[0].price_versions[0].id).toBe(91)
    expect(mocks.listRoutePriceVersions).toHaveBeenCalledWith({ route_version_id: 82 })
  })

  it('creates V1 and revisions through versioned commands with exact copied nodes', async () => {
    const draft = version({ id: 82, version: 2, status: 'draft', row_version: 0 })
    mocks.createVersionedRoute.mockResolvedValue({ root, version: draft })
    mocks.createRouteRevision.mockResolvedValue(draft)
    mocks.listRouteVersions.mockResolvedValue({ route: root, versions: [draft], events: [] })

    const state = useRouteVersions()
    await state.createRoute({ ...draft, revision_reason: '建立路线主数据' })
    expect(mocks.createVersionedRoute).toHaveBeenCalledWith(expect.objectContaining({
      name: '标准机加工路线',
      category: '机加工',
      revision_reason: '建立路线主数据',
      idempotency_key: expect.stringMatching(/^route-create:/),
      items: [{
        process_id: 7,
        process_version_id: 71,
        seq_order: 10,
        is_required: 1,
        required_audit: 1,
      }],
    }))

    state.root.value = root
    state.selectedVersion.value = version()
    await state.createRevision({ ...version(), revision_reason: '调整节点审批要求' })
    expect(mocks.createRouteRevision).toHaveBeenCalledWith(8, expect.objectContaining({
      row_version: 5,
      revision_reason: '调整节点审批要求',
      idempotency_key: expect.stringMatching(/^route-revision:/),
      items: [expect.objectContaining({ process_version_id: 71, required_audit: 1 })],
    }))
  })

  it('blocks approval until every node has an explicit exact price disposition', async () => {
    const pending = version({ status: 'pending_approval', row_version: 4 })
    mocks.approveRouteVersion.mockResolvedValue({ ...pending, status: 'published' })
    mocks.listRouteVersions.mockResolvedValue({ route: root, versions: [pending], events: [] })

    const state = useRouteVersions()
    state.root.value = root
    state.versions.value = [pending]
    state.selectedVersion.value = pending

    await expect(state.approveSelected([])).rejects.toThrow('工价处置')
    expect(mocks.approveRouteVersion).not.toHaveBeenCalled()

    await state.approveSelected([{
      process_id: 7,
      disposition: 'not_applicable',
      reason: '该节点按计时工资结算',
    }])
    expect(mocks.approveRouteVersion).toHaveBeenCalledWith(81, {
      row_version: 4,
      idempotency_key: expect.stringMatching(/^route-approve:/),
      required_price_process_ids: [7],
      price_dispositions: [{
        process_id: 7,
        disposition: 'not_applicable',
        reason: '该节点按计时工资结算',
      }],
    })
  })
})

describe('route version API and editor', () => {
  beforeEach(() => {
    mocks.request.mockReset()
    mocks.request.mockResolvedValue({})
  })

  it('uses only route version and lifecycle write endpoints', async () => {
    const payload = { row_version: 2, idempotency_key: 'route-command-123' }
    await processRouteVersionsApi.createVersionedRoute(payload)
    await processRouteVersionsApi.createRouteRevision(8, payload)
    await processRouteVersionsApi.updateRouteVersion(82, payload)
    await processRouteVersionsApi.submitRouteVersion(82, payload)
    await processRouteVersionsApi.approveRouteVersion(82, payload)
    await processRouteVersionsApi.rejectRouteVersion(82, payload)
    await processRouteVersionsApi.requestRouteRetirement(8, payload)
    await processRouteVersionsApi.requestRouteReactivation(8, payload)

    expect(mocks.request.mock.calls).toEqual([
      ['POST', '/api/process-route-versions', payload],
      ['POST', '/api/process-routes/8/revisions', payload],
      ['PUT', '/api/process-route-versions/82', payload],
      ['POST', '/api/process-route-versions/82/submit', payload],
      ['POST', '/api/process-route-versions/82/approve', payload],
      ['POST', '/api/process-route-versions/82/reject', payload],
      ['POST', '/api/process-routes/8/retirement-requests', payload],
      ['POST', '/api/process-routes/8/reactivation-requests', payload],
    ])
  })

  it('keeps published content read-only and offers only same-category published processes', async () => {
    const wrapper = mount(RouteVersionEditor, {
      props: {
        modelValue: version(),
        readonly: true,
        processOptions: [
          { id: 7, process_version_id: 71, process_version: 3, process_name: '精车', category: '机加工', version_status: 'published' },
          { id: 9, process_version_id: 91, process_version: 1, process_name: '焊接', category: '结构件', version_status: 'published' },
          { id: 10, process_version_id: 101, process_version: 2, process_name: '旧车削', category: '机加工', version_status: 'superseded' },
        ],
      },
    })
    await flushPromises()

    expect(wrapper.findAll('input').every(input => input.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findAll('select').every(select => select.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.text()).toContain('精车')
    expect(wrapper.text()).not.toContain('焊接')
    expect(wrapper.text()).not.toContain('旧车削')
  })
})
