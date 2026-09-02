import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PriceVersionTab from '@/views/wage/PriceVersionTab.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listVersions: vi.fn(),
  listReferences: vi.fn(),
  createVersion: vi.fn(),
  approveVersion: vi.fn(),
  voidVersion: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      wages: {
        listRoutePriceVersions: mocks.listVersions,
        getRoutePriceVersionReference: mocks.listReferences,
        createRoutePriceVersion: mocks.createVersion,
        approveRoutePriceVersion: mocks.approveVersion,
        voidRoutePriceVersion: mocks.voidVersion,
      },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  can: vi.fn(permission => mocks.permissions.has(permission)),
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


const references = [
  {
    reference_key: '81:71', route_id: 8, route_version_id: 81, route_version: 1,
    route_name: '标准机加工路线', route_category: '机加工',
    route_version_status: 'published', route_content_digest: 'route-v1',
    process_id: 7, process_version_id: 71, process_version: 1,
    process_name: '精车', process_version_status: 'published',
    process_content_digest: 'process-v1', seq_order: 10,
    pricing_mode: 'published_adjustment',
  },
  {
    reference_key: '82:72', route_id: 8, route_version_id: 82, route_version: 2,
    route_name: '标准机加工路线', route_category: '机加工',
    route_version_status: 'pending_approval', route_content_digest: 'route-v2',
    process_id: 7, process_version_id: 72, process_version: 2,
    process_name: '精车二序', process_version_status: 'pending_approval',
    process_content_digest: 'process-v2', seq_order: 20,
    pricing_mode: 'pending_group_release',
  },
]

const versions = [
  {
    id: 101, route_id: 8, route_version_id: 81,
    route_name: '标准机加工路线', process_id: 7, process_version_id: 71,
    process_name: '精车', normal_unit_price_micros: 100000,
    valid_from: '2026-01-01 07:00:00', valid_to: '', status: 'approved',
    row_version: 1,
  },
  {
    id: 102, route_id: 8, route_version_id: 82,
    route_name: '标准机加工路线', process_id: 7, process_version_id: 72,
    process_name: '精车二序', normal_unit_price_micros: 125000,
    valid_from: '2026-09-01 07:00:00', valid_to: '', status: 'draft',
    created_by_name: '制单人甲', row_version: 0,
  },
  {
    id: 103, route_id: 8, route_version_id: 82,
    route_name: '标准机加工路线', process_id: 7, process_version_id: 72,
    process_name: '精车二序', normal_unit_price_micros: 120000,
    valid_from: '2026-08-20 07:00:00', status: 'voided',
    void_reason: '路线节点调整', voided_at: '2026-08-24 09:30:00',
    voided_by_name: '杜斌', row_version: 1,
  },
]


describe('PriceVersionTab exact-version workflow', () => {
  beforeEach(() => {
    mocks.permissions = new Set(['wages:prepare', 'wages:approve'])
    mocks.listVersions.mockReset().mockResolvedValue({ versions })
    mocks.listReferences.mockReset().mockResolvedValue({ items: references })
    mocks.createVersion.mockReset().mockResolvedValue({ id: 301, status: 'draft' })
    mocks.approveVersion.mockReset().mockResolvedValue({ id: 102, status: 'approved' })
    mocks.voidVersion.mockReset().mockResolvedValue({ id: 102, status: 'voided' })
    mocks.showToast.mockReset()
  })

  it('keeps published and pending revisions as independent exact references', async () => {
    const wrapper = mount(PriceVersionTab)
    await flushPromises()

    expect(mocks.listReferences).toHaveBeenCalledWith({ include_pending: true })
    expect(wrapper.find('[data-testid="view-published"]').classes()).toContain('active')
    expect(wrapper.find('[data-testid="reference-row-81:71"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('标准机加工路线 · 当前 V1')

    await wrapper.find('[data-testid="view-pending-route"]').trigger('click')
    expect(wrapper.find('[data-testid="reference-row-82:72"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('标准机加工路线 · 待发布 V2')
    expect(wrapper.text()).toContain('只能随路线成组发布')
    expect(wrapper.find('[data-testid="approve-price-102"]').exists()).toBe(false)
  })

  it('creates a pending price with locked version IDs and digest snapshots', async () => {
    mocks.listVersions.mockResolvedValue({ versions: versions.filter(item => item.id !== 102) })
    const wrapper = mount(PriceVersionTab)
    await flushPromises()

    await wrapper.find('[data-testid="view-pending-route"]').trigger('click')
    await wrapper.find('[data-testid="create-price-82:72"]').trigger('click')
    const editor = wrapper.find('[data-testid="price-version-editor"]')
    expect(editor.find('[data-testid="locked-route"]').attributes('disabled')).toBeDefined()
    expect(editor.find('[data-testid="locked-process"]').attributes('disabled')).toBeDefined()
    await editor.find('[data-testid="price-unit-input"]').setValue('13.7500')
    await editor.find('[data-testid="price-remark-input"]').setValue('新路线精确定价')
    await editor.find('[data-testid="save-price-draft"]').trigger('click')
    await flushPromises()

    expect(mocks.createVersion).toHaveBeenCalledWith(expect.objectContaining({
      route_id: 8, route_version_id: 82, process_id: 7, process_version_id: 72,
      expected_route_content_digest: 'route-v2',
      expected_process_content_digest: 'process-v2',
      normal_unit_price: '13.75', remark: '新路线精确定价',
      idempotency_key: expect.stringMatching(/^route-price-create:/),
    }))
  })

  it('voids a draft through the shared editor and keeps voided history read-only', async () => {
    const wrapper = mount(PriceVersionTab)
    await flushPromises()

    await wrapper.find('[data-testid="view-pending-route"]').trigger('click')
    await wrapper.find('[data-testid="edit-price-102"]').trigger('click')
    const editor = wrapper.find('[data-testid="price-version-editor"]')
    await editor.find('[data-testid="void-reason-input"]').setValue('金额录入错误')
    await editor.find('[data-testid="void-price-draft"]').trigger('click')
    await flushPromises()
    expect(mocks.voidVersion).toHaveBeenCalledWith(102, expect.objectContaining({
      row_version: 0, reason: '金额录入错误',
      idempotency_key: expect.stringMatching(/^route-price-void:/),
    }))

    await wrapper.find('[data-testid="view-voided"]').trigger('click')
    expect(wrapper.text()).toContain('路线节点调整')
    expect(wrapper.text()).toContain('杜斌')
    expect(wrapper.find('[data-testid="create-price-82:72"]').exists()).toBe(false)
  })
})
