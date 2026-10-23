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
  removeReleaseBatchMember: vi.fn(),
  replaceReleaseBatchMember: vi.fn(),
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

  it('repairs a draft member with exact IDs, row version, and idempotency', async () => {
    mocks.replaceReleaseBatchMember.mockResolvedValue(batch({ status: 'draft', row_version: 1 }))
    const state = useMasterDataReleases()
    state.selectedBatch.value = batch({ status: 'draft', row_version: 0 })
    await state.replaceMember('price_version', 92, 93, '替换已作废工价')
    expect(mocks.replaceReleaseBatchMember).toHaveBeenCalledWith(41, {
      member_type: 'price_version',
      member_id: 92,
      replacement_member_id: 93,
      row_version: 0,
      reason: '替换已作废工价',
      idempotency_key: expect.stringMatching(/^release-member-replace:/),
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

  it('uses the latest reactive route and only its exact draft prices when creating a batch', async () => {
    mocks.permissions = new Set(['master_data_releases:view', 'master_data_releases:create'])
    mocks.createReleaseBatch.mockResolvedValue(batch({ status: 'draft' }))
    const wrapper = mount(ReleaseBatchPanel, {
      props: { defaultRouteVersion: { id: 1, name: '旧路线', version: 1, items: [] } },
    })
    await flushPromises()
    await wrapper.setProps({
      defaultRouteVersion: {
        id: 82, name: '标准机加工路线', version: 2,
        items: [
          { process_version_id: 72, process_version_status: 'pending_approval' },
          { process_version_id: 72, process_version_status: 'pending_approval' },
          { process_version_id: 73, process_version_status: 'published' },
        ],
      },
      defaultPriceVersions: [
        { id: 92, route_version_id: 82, process_version_id: 72, status: 'draft' },
        { id: 93, route_version_id: 1, process_version_id: 72, status: 'draft' },
        { id: 94, route_version_id: 82, process_version_id: 99, status: 'draft' },
        { id: 95, route_version_id: 82, process_version_id: 72, status: 'approved' },
      ],
    })

    await wrapper.findAll('button').find(button => button.text() === '新建发布批次').trigger('click')
    expect(wrapper.find('.create-scope').text()).toContain('工序版本 1')
    await wrapper.findAll('button').find(button => button.text() === '创建草稿批次').trigger('click')
    await flushPromises()

    expect(mocks.createReleaseBatch).toHaveBeenCalledWith(expect.objectContaining({
      revision_reason: '发布路线 标准机加工路线 V2',
      process_version_ids: [72], route_version_ids: [82], price_version_ids: [92],
      idempotency_key: expect.stringMatching(/^release-create:/),
    }))
    wrapper.unmount()
  })

  it.each([false, true])('emits publication only after a successful approval (failure=%s)', async failure => {
    const published = batch({ status: 'published', row_version: 3 })
    if (failure) mocks.approveReleaseBatch.mockRejectedValue(new Error('发布依赖校验失败'))
    else mocks.approveReleaseBatch.mockResolvedValue(published)
    const wrapper = mount(ReleaseBatchPanel)
    await flushPromises()
    await wrapper.find('.batch-row').trigger('click')
    await flushPromises()
    await wrapper.find('.disposition-row select').setValue('price_version')
    await wrapper.findAll('.disposition-row select')[1].setValue('92')
    await wrapper.findAll('button').find(button => button.text() === '批准并原子发布').trigger('click')
    await flushPromises()

    expect(mocks.approveReleaseBatch).toHaveBeenCalledWith(41, expect.objectContaining({
      row_version: 2,
      price_dispositions: [{ process_id: 7, disposition: 'price_version', price_version_id: 92 }],
      idempotency_key: expect.stringMatching(/^release-approve:/),
    }))
    if (failure) {
      expect(wrapper.emitted('published')).toBeUndefined()
      expect(wrapper.text()).toContain('发布依赖校验失败')
      expect(mocks.showToast).toHaveBeenCalledWith('发布依赖校验失败', 'error')
    } else {
      expect(wrapper.emitted('published')).toEqual([[published]])
      expect(mocks.showToast).toHaveBeenCalledWith('主数据批次已原子发布')
    }
    expect(wrapper.emitted('busy-change')).toEqual([[false], [true], [false]])
    wrapper.unmount()
  })

  it('hides command controls from a viewer with no create or approval permission', async () => {
    mocks.permissions = new Set(['master_data_releases:view'])
    const wrapper = mount(ReleaseBatchPanel)
    await flushPromises()
    await wrapper.find('.batch-row').trigger('click')
    await flushPromises()

    const labels = wrapper.findAll('button').map(button => button.text())
    expect(labels).not.toContain('新建发布批次')
    expect(labels).not.toContain('批准并原子发布')
    expect(labels).not.toContain('驳回')
    expect(mocks.approveReleaseBatch).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('names invalid draft members and blocks submit until repaired', async () => {
    mocks.permissions = new Set(['master_data_releases:view', 'master_data_releases:submit'])
    const invalid = batch({
      status: 'draft',
      row_version: 0,
      price_versions: [{
        id: 92, route_version_id: 82, process_version_id: 72, status: 'voided',
      }],
    })
    mocks.listReleaseBatches.mockResolvedValue([invalid])
    mocks.getReleaseBatch.mockResolvedValue(invalid)
    const wrapper = mount(ReleaseBatchPanel)
    await flushPromises()
    await wrapper.find('.batch-row').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="invalid-release-members"]').text()).toContain('工价 #92 已作废')
    const submit = wrapper.findAll('button').find(button => button.text() === '提交审批')
    expect(submit.attributes('disabled')).toBeDefined()
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
    await masterDataReleasesApi.removeReleaseBatchMember(41, payload)
    await masterDataReleasesApi.replaceReleaseBatchMember(41, payload)

    expect(mocks.request.mock.calls).toEqual([
      ['GET', '/api/master-data-release-batches'],
      ['GET', '/api/master-data-release-batches/41'],
      ['POST', '/api/master-data-release-batches', payload],
      ['POST', '/api/master-data-release-batches/41/submit', payload],
      ['POST', '/api/master-data-release-batches/41/approve', payload],
      ['POST', '/api/master-data-release-batches/41/reject', payload],
      ['POST', '/api/master-data-release-batches/41/members/remove', payload],
      ['POST', '/api/master-data-release-batches/41/members/replace', payload],
    ])
  })
})
