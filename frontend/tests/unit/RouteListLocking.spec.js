import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RouteList from '@/views/RouteList.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listProcessRoutes: vi.fn(),
  listProcesses: vi.fn(),
  listRouteVersions: vi.fn(),
  getRouteVersionImpact: vi.fn(),
  listRoutePriceVersions: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      processRoutes: { listProcessRoutes: mocks.listProcessRoutes },
      processes: { listProcesses: mocks.listProcesses },
      processRouteVersions: {
        listRouteVersions: mocks.listRouteVersions,
        getRouteVersionImpact: mocks.getRouteVersionImpact,
      },
      wages: { listRoutePriceVersions: mocks.listRoutePriceVersions },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  can: vi.fn(permission => mocks.permissions.has(permission)),
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

const published = {
  id: 11,
  process_route_id: 1,
  version: 1,
  name: '已引用路线',
  category: '结构件',
  status: 'published',
  row_version: 1,
  items: [],
}

describe('RouteList versioned changes', () => {
  beforeEach(() => {
    mocks.permissions = new Set(['routes:view', 'route_versions:create', 'process_routes:retire'])
    Object.values(mocks).filter(value => typeof value?.mockReset === 'function').forEach(mock => mock.mockReset())
    mocks.listProcesses.mockResolvedValue({ processes: [] })
    mocks.getRouteVersionImpact.mockResolvedValue({ impact: { total_references: 3, references: [] } })
    mocks.listRoutePriceVersions.mockResolvedValue({ versions: [] })
    mocks.listRouteVersions.mockResolvedValue({
      route: { id: 1, route_code: 'ROUTE-0001', lifecycle_status: 'active', current_effective_version_id: 11, row_version: 3 },
      versions: [published],
      events: [],
    })
    mocks.listProcessRoutes.mockResolvedValue({
      routes: [
        { id: 1, route_code: 'ROUTE-0001', name: '已引用路线', category: '结构件', lifecycle_status: 'active', route_version: 1, version_status: 'published', processes: [], used_orders: 2, used_products: 1, is_locked: true },
        { id: 2, route_code: 'ROUTE-0002', name: '未引用路线', category: '结构件', lifecycle_status: 'active', route_version: 1, version_status: 'published', processes: [], used_orders: 0, used_products: 0, is_locked: false },
      ],
      total: 2,
      summary: { total_routes: 49, category_counts: { '结构件': 43, '机加工': 6 }, process_nodes_total: 296 },
    })
  })

  it('keeps references visible and replaces edit/delete with revision and retirement', async () => {
    const wrapper = mount(RouteList)
    await flushPromises()

    expect(wrapper.text()).toContain('订单 2 / 产品 1')
    expect(wrapper.find('[data-testid="route-edit-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="route-delete-1"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="route-revision-1"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="route-revision-2"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('申请退休')
    expect(wrapper.text()).toContain('49')
    expect(wrapper.text()).toContain('296')
  })

  it('allows an already referenced route to enter the revision workflow', async () => {
    const wrapper = mount(RouteList)
    await flushPromises()

    await wrapper.get('[data-testid="route-revision-1"]').trigger('click')
    await flushPromises()

    expect(mocks.listRouteVersions).toHaveBeenCalledWith(1)
    expect(wrapper.text()).toContain('创建路线修订版')
    expect(wrapper.find('.command-modal').exists()).toBe(true)
  })
})
