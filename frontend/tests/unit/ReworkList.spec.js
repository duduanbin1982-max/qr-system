import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReworkList from '@/views/ReworkList.vue'


const mocks = vi.hoisted(() => ({
  listRework: vi.fn(),
  reworkStats: vi.fn(),
  completeRework: vi.fn(),
  batchCompleteRework: vi.fn(),
  updateRework: vi.fn(),
  listUsers: vi.fn(),
  listProcesses: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      rework: {
        listRework: mocks.listRework,
        reworkStats: mocks.reworkStats,
        completeRework: mocks.completeRework,
        batchCompleteRework: mocks.batchCompleteRework,
        updateRework: mocks.updateRework,
      },
      users: { listUsers: mocks.listUsers },
      processes: { listProcesses: mocks.listProcesses },
    },
  },
}))

vi.mock('@/lib/auth.js', () => ({ can: vi.fn(() => true) }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


const pendingItem = {
  id: 1,
  order_no: 'RW-001',
  product_name: '返工产品',
  customer_name: '测试客户',
  process_name: '焊接',
  worker_name: '返工员工',
  quantity: 2,
  reason: '焊点异常',
  status: 'pending',
  created_at: '2026-07-31 06:00:00',
}

const completedItem = {
  ...pendingItem,
  id: 2,
  status: 'completed',
  completed_by_name: '管理员',
  result: 'ok',
  duration_hours: 1.5,
  completed_at: '2026-07-31 07:30:00',
}


describe('ReworkList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listRework.mockImplementation(params => Promise.resolve({
      ok: true,
      items: params.status === 'completed' ? [completedItem] : [pendingItem],
      total: 1,
    }))
    mocks.reworkStats.mockResolvedValue({ ok: true, pending_count: 1, pending_qty: 2 })
    mocks.listUsers.mockResolvedValue({ users: [] })
    mocks.listProcesses.mockResolvedValue({ processes: [] })
    mocks.updateRework.mockResolvedValue({ ok: true })
    mocks.batchCompleteRework.mockResolvedValue({ ok: true, completed: 1, errors: [] })
  })

  it('keeps completed table headers aligned with data cells', async () => {
    const wrapper = mount(ReworkList)
    await flushPromises()

    await wrapper.vm.switchTab('completed')
    await flushPromises()
    const table = wrapper.find('table')
    expect(table.findAll('thead th')).toHaveLength(10)
    expect(table.findAll('tbody tr').at(0).findAll('td')).toHaveLength(10)
    expect(table.findAll('thead th').at(0).text()).toBe('订单号')
  })

  it('submits a single completion request while one is pending', async () => {
    let resolveComplete
    mocks.completeRework.mockImplementation(() => new Promise(resolve => {
      resolveComplete = resolve
    }))
    const wrapper = mount(ReworkList)
    await flushPromises()

    wrapper.vm.openComplete(pendingItem)
    const first = wrapper.vm.doComplete()
    const second = wrapper.vm.doComplete()
    expect(mocks.completeRework).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.completeSubmitting).toBe(true)

    resolveComplete({ ok: true })
    await Promise.all([first, second])
    await flushPromises()
    expect(wrapper.vm.completeSubmitting).toBe(false)
  })

  it('does not mutate the displayed reason when editing is cancelled', async () => {
    const wrapper = mount(ReworkList)
    await flushPromises()
    const item = wrapper.vm.items[0]

    wrapper.vm.startEdit(item)
    wrapper.vm.editReason = '临时修改'
    wrapper.vm.cancelEdit()

    expect(item.reason).toBe('焊点异常')
  })

  it('ignores a superseded list response', async () => {
    let resolveFirst
    let resolveSecond
    mocks.listRework
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
    const wrapper = mount(ReworkList)

    const latest = wrapper.vm.load(1)
    resolveSecond({ ok: true, items: [{ ...pendingItem, id: 9, reason: '新结果' }], total: 1 })
    await latest
    resolveFirst({ ok: true, items: [{ ...pendingItem, id: 8, reason: '旧结果' }], total: 1 })
    await flushPromises()

    expect(wrapper.vm.items[0].reason).toBe('新结果')
  })
})
