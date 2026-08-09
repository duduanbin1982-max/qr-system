import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PriceVersionTab from '@/views/wage/PriceVersionTab.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listVersions: vi.fn(),
  listReferences: vi.fn(),
  createVersion: vi.fn(),
  approveVersion: vi.fn(),
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
      },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  can: vi.fn(permission => mocks.permissions.has(permission)),
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


const references = [
  { route_id: 1, route_name: '车工路线', route_category: '机加工', process_id: 11, process_name: '车削', seq_order: 1 },
  { route_id: 1, route_name: '车工路线', route_category: '机加工', process_id: 12, process_name: '钻孔', seq_order: 2 },
  { route_id: 2, route_name: '铣工路线', route_category: '机加工', process_id: 21, process_name: '铣削', seq_order: 1 },
]

const versions = [
  {
    id: 101,
    route_id: 1,
    route_name: '车工路线',
    process_id: 11,
    process_name: '车削',
    normal_unit_price_micros: 100000,
    rework_rate_basis_points: 5000,
    rework_rate_configured: 1,
    valid_from: '2026-01-01 07:00:00',
    valid_to: '',
    status: 'approved',
    created_by_name: '制单人甲',
    approved_by_name: '审批人乙',
    row_version: 1,
  },
  {
    id: 102,
    route_id: 1,
    route_name: '车工路线',
    process_id: 11,
    process_name: '车削',
    normal_unit_price_micros: 120000,
    rework_rate_basis_points: 6000,
    rework_rate_configured: 1,
    valid_from: '2099-09-01 07:00:00',
    valid_to: '',
    status: 'draft',
    created_by_name: '制单人甲',
    created_at: '2026-08-09 09:30:00',
    remark: '调价通知 2026-08',
    row_version: 3,
  },
  {
    id: 201,
    route_id: 2,
    route_name: '铣工路线',
    process_id: 21,
    process_name: '铣削',
    normal_unit_price_micros: 80000,
    rework_rate_basis_points: 0,
    rework_rate_configured: 0,
    valid_from: '2026-01-01 07:00:00',
    valid_to: '',
    status: 'approved',
    created_by_name: '制单人甲',
    approved_by_name: '审批人乙',
    row_version: 1,
  },
]


describe('PriceVersionTab workflow', () => {
  beforeEach(() => {
    mocks.permissions = new Set(['wages:prepare', 'wages:approve'])
    mocks.listVersions.mockReset().mockResolvedValue({ versions })
    mocks.listReferences.mockReset().mockResolvedValue({ items: references })
    mocks.createVersion.mockReset().mockResolvedValue({ id: 301 })
    mocks.approveVersion.mockReset().mockResolvedValue({ id: 102, status: 'approved' })
    mocks.showToast.mockReset()
  })

  it('opens with route cards and expands one route at a time', async () => {
    const wrapper = mount(PriceVersionTab)
    await flushPromises()

    expect(wrapper.find('[data-testid="view-current"]').classes()).toContain('active')
    expect(wrapper.findAll('[data-testid^="route-price-card-"]')).toHaveLength(2)
    expect(wrapper.findAll('.current-table tbody tr')).toHaveLength(0)
    await wrapper.find('[data-testid="route-price-card-1"] button').trigger('click')
    expect(wrapper.findAll('.current-table tbody tr')).toHaveLength(2)
    expect(wrapper.text()).toContain('当前有效')
    expect(wrapper.text()).toContain('待审批')
    expect(wrapper.text()).toContain('未设置')
    expect(wrapper.text()).toContain('1 个草稿待处理')
    wrapper.unmount()
  })

  it('prefills route, process and current values when starting a price change', async () => {
    const wrapper = mount(PriceVersionTab)
    await flushPromises()

    await wrapper.find('[data-testid="route-price-card-2"] button').trigger('click')
    await wrapper.find('[data-testid="change-price-2-21"]').trigger('click')
    const modal = wrapper.find('.price-modal')
    const selects = modal.findAll('select')
    expect(selects[0].element.value).toBe('2')
    expect(selects[1].element.value).toBe('21')
    expect(selects[0].attributes('disabled')).toBeDefined()
    expect(modal.find('input[type="number"]').element.value).toBe('8.0000')

    await modal.find('input[type="number"]').setValue('9.2500')
    await modal.find('textarea').setValue('新工艺定价')
    await modal.find('[data-testid="save-price-draft"]').trigger('click')
    await flushPromises()

    expect(mocks.createVersion).toHaveBeenCalledWith(expect.objectContaining({
      route_id: 2,
      process_id: 21,
      normal_unit_price: 9.25,
      remark: '新工艺定价',
    }))
    expect(wrapper.find('[data-testid="view-pending"]').classes()).toContain('active')
    wrapper.unmount()
  })

  it('shows the price difference before approving a draft', async () => {
    const wrapper = mount(PriceVersionTab)
    await flushPromises()

    await wrapper.find('[data-testid="view-pending"]').trigger('click')
    await wrapper.find('[data-testid="approve-price-102"]').trigger('click')

    const modal = wrapper.find('.approval-modal')
    expect(modal.text()).toContain('¥10.0000')
    expect(modal.text()).toContain('¥12.0000')
    expect(modal.text()).toContain('+¥2.0000')
    expect(modal.text()).toContain('调价通知 2026-08')

    await modal.find('[data-testid="confirm-price-approval"]').trigger('click')
    await flushPromises()
    expect(mocks.approveVersion).toHaveBeenCalledWith(102, 3)
    wrapper.unmount()
  })
})
