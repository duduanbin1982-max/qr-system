import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RouteList from '@/views/RouteList.vue'


const mocks = vi.hoisted(() => ({
  permissions: new Set(),
  listProcessRoutes: vi.fn(),
  listProcesses: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      processRoutes: {
        listProcessRoutes: mocks.listProcessRoutes,
      },
      processes: {
        listProcesses: mocks.listProcesses,
      },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({
  can: vi.fn(permission => mocks.permissions.has(permission)),
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


describe('RouteList reference locking', () => {
  beforeEach(() => {
    mocks.permissions = new Set(['routes:view', 'routes:edit', 'routes:delete'])
    mocks.listProcessRoutes.mockReset()
    mocks.listProcesses.mockReset()
    mocks.showToast.mockReset()
    mocks.listProcesses.mockResolvedValue({ processes: [] })
    mocks.listProcessRoutes.mockResolvedValue({
      routes: [
        {
          id: 1,
          name: '已引用路线',
          status: 'active',
          processes: [],
          used_orders: 2,
          used_products: 1,
          is_locked: true,
        },
        {
          id: 2,
          name: '未引用路线',
          status: 'active',
          processes: [],
          used_orders: 0,
          used_products: 0,
          is_locked: false,
        },
      ],
      total: 2,
      summary: {
        total_routes: 49,
        category_counts: { '结构件': 43, '机加工': 6 },
        process_nodes_total: 296,
      },
    })
  })

  it('shows reference counts and disables changes for locked routes', async () => {
    const wrapper = mount(RouteList)
    await flushPromises()

    expect(wrapper.text()).toContain('订单引用 2 · 产品引用 1')
    expect(wrapper.get('[data-testid="route-edit-1"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="route-delete-1"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="route-edit-1"]').attributes('title')).toContain('不能修改或删除')
    expect(wrapper.get('[data-testid="route-edit-2"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="route-delete-2"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('49')
    expect(wrapper.text()).toContain('296')
  })

  it('guards programmatic edit attempts for locked routes', async () => {
    const wrapper = mount(RouteList)
    await flushPromises()

    wrapper.vm.openEdit({
      id: 1,
      is_locked: true,
      used_orders: 2,
      used_products: 1,
    })

    expect(wrapper.vm.showModal).toBe(false)
    expect(mocks.showToast).toHaveBeenCalledWith(
      '已被2 个订单、1 个产品引用，不能修改或删除；请新建路线供后续业务使用',
      'warn',
    )
  })
})
