import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useMasterDataReleases } from '@/composables/useMasterDataReleases.js'
import { masterDataReleasesApi } from '@/lib/api/master-data-releases.js'
import ReleaseBatchPanel from '@/components/master-data/ReleaseBatchPanel.vue'


const mocks = vi.hoisted(() => ({
  listReleaseBatches: vi.fn(),
  getReleaseBatch: vi.fn(),
  createReleaseBatch: vi.fn(),
  submitReleaseBatch: vi.fn(),
  approveReleaseBatch: vi.fn(),
  rejectReleaseBatch: vi.fn(),
  request: vi.fn(),
  permissions: new Set(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { masterDataReleases: mocks } },
}))
vi.mock('@/lib/api/client.js', () => ({ request: mocks.request, buildQuery: vi.fn(() => '') }))
vi.mock('@/lib/auth.js', () => ({ can: vi.fn(permission => mocks.permissions.has(permission)) }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

function batch(overrides = {}) {
  return {
    id: 41,
    release_no: 'MDR-20260815-01',
    revision_reason: '工序路线与工价同步发布',
    status: 'pending_approval',
    row_version: 2,
    process_versions: [{ id: 72, process_id: 7, version: 2, name: '精车二序', status: 'pending_approval' }],
    route_versions: [{
      id: 82,
      process_route_id: 8,
      version: 2,
      name: '标准机加工路线',
      status: 'pending_approval',
      items: [{ process_id: 7, process_version_id: 72, process_name_snapshot: '精车二序' }],
    }],
    price_versions: [{ id: 92, route_version_id: 82, process_id: 7, process_version_id: 72, status: 'draft' }],
    ...overrides,
  }
}

describe('useMasterDataReleases', () => {
  beforeEach(() => {
    Object.values(mocks).filter(value => typeof value?.mockReset === 'function').forEach(mock => mock.mockReset())
    mocks.permissions = new Set(['master_data_releases:view', 'master_data_releases:approve'])
    mocks.listReleaseBatches.mockResolvedValue([batch()])
    mocks.getReleaseBatch.mockResolvedValue(batch())
  })

  it('creates a dependency-complete batch with one idempotent command', async () => {
    mocks.createReleaseBatch.mockResolvedValue(batch({ status: 'draft', row_version: 0 }))
    const state = useMasterDataReleases()

    await state.createBatch({
      release_no: 'MDR-20260815-01',
      revision_reason: '工序路线与工价同步发布',
      process_version_ids: [72],
      route_version_ids: [82],
      price_version_ids: [92],
    })

    expect(mocks.createReleaseBatch).toHaveBeenCalledOnce()
    expect(mocks.createReleaseBatch).toHaveBeenCalledWith(expect.objectContaining({
      process_version_ids: [72],
      route_version_ids: [82],
      price_version_ids: [92],
      idempotency_key: expect.stringMatching(/^release-create:/),
    }))
  })

  it('sends one approval request on duplicate clicks', async () => {
    let finish
    mocks.approveReleaseBatch.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const state = useMasterDataReleases()
    state.selectedBatch.value = batch()

    const command = [{ process_id: 7, disposition: 'price_version', price_version_id: 92 }]
    const first = state.approveBatch(command)
    const duplicate = state.approveBatch(command)

    await expect(duplicate).resolves.toBeNull()
    expect(mocks.approveReleaseBatch).toHaveBeenCalledOnce()
    finish(batch({ status: 'published', row_version: 3 }))
    await first
  })

  it('refreshes the complete batch after an approval conflict', async () => {
    const conflict = Object.assign(new Error('发布依赖已变化'), { status: 409 })
    mocks.approveReleaseBatch.mockRejectedValue(conflict)
    const state = useMasterDataReleases()
    state.selectedBatch.value = batch()

    await expect(state.approveBatch([
      { process_id: 7, disposition: 'price_version', price_version_id: 92 },
    ])).rejects.toThrow('发布依赖已变化')

    expect(mocks.getReleaseBatch).toHaveBeenCalledWith(41)
    expect(state.selectedBatch.value.id).toBe(41)
  })

  it('rejects missing price dispositions before publication', () => {
    const state = useMasterDataReleases()
    state.selectedBatch.value = batch()
    expect(() => state.validatePriceDispositions([])).toThrow('工价处置')
    expect(state.validatePriceDispositions([
      { process_id: 7, disposition: 'price_version', price_version_id: 92 },
    ])).toEqual({
      required_price_process_ids: [7],
      price_dispositions: [{ process_id: 7, disposition: 'price_version', price_version_id: 92 }],
    })
  })

  it('renders complete dependencies and keeps approval disabled until price disposition is complete', async () => {
    const wrapper = mount(ReleaseBatchPanel)
    await flushPromises()
    await wrapper.find('.batch-row').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('精车二序')
    expect(wrapper.text()).toContain('标准机加工路线')
    expect(wrapper.text()).toContain('工价版本依赖')
    const approve = wrapper.findAll('button').find(button => button.text() === '批准并原子发布')
    expect(approve.attributes('disabled')).toBeDefined()

    const disposition = wrapper.find('.disposition-row select')
    await disposition.setValue('price_version')
    await flushPromises()
    const priceSelects = wrapper.findAll('.disposition-row select')
    await priceSelects[1].setValue('92')
    await flushPromises()
    expect(approve.attributes('disabled')).toBeUndefined()
  })
})

describe('master-data release API', () => {
  beforeEach(() => {
    mocks.request.mockReset()
    mocks.request.mockResolvedValue({})
  })

  it('maps the complete release workflow', async () => {
    const payload = { row_version: 2, idempotency_key: 'release-command-123' }
    await masterDataReleasesApi.listReleaseBatches({ status: 'draft' })
    await masterDataReleasesApi.getReleaseBatch(41)
    await masterDataReleasesApi.createReleaseBatch(payload)
    await masterDataReleasesApi.submitReleaseBatch(41, payload)
    await masterDataReleasesApi.approveReleaseBatch(41, payload)
    await masterDataReleasesApi.rejectReleaseBatch(41, payload)

    expect(mocks.request.mock.calls).toEqual([
      ['GET', '/api/master-data-release-batches'],
      ['GET', '/api/master-data-release-batches/41'],
      ['POST', '/api/master-data-release-batches', payload],
      ['POST', '/api/master-data-release-batches/41/submit', payload],
      ['POST', '/api/master-data-release-batches/41/approve', payload],
      ['POST', '/api/master-data-release-batches/41/reject', payload],
    ])
  })
})
