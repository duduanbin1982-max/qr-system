import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProductionNodes } from '@/composables/gantt/useProductionNodes.js'


const mocks = vi.hoisted(() => ({
  listProductionNodes: vi.fn(),
  listScheduleCalendars: vi.fn(),
  createProductionNode: vi.fn(),
  updateProductionNode: vi.fn(),
  listProductionNodeCapabilities: vi.fn(),
  replaceProductionNodeCapabilities: vi.fn(),
  listProductionNodeOverrides: vi.fn(),
  createProductionNodeOverride: vi.fn(),
  cancelProductionNodeOverride: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      production: {
        listProductionNodes: mocks.listProductionNodes,
        listScheduleCalendars: mocks.listScheduleCalendars,
        createProductionNode: mocks.createProductionNode,
        updateProductionNode: mocks.updateProductionNode,
        listProductionNodeCapabilities: mocks.listProductionNodeCapabilities,
        replaceProductionNodeCapabilities: mocks.replaceProductionNodeCapabilities,
        listProductionNodeOverrides: mocks.listProductionNodeOverrides,
        createProductionNodeOverride: mocks.createProductionNodeOverride,
        cancelProductionNodeOverride: mocks.cancelProductionNodeOverride,
      },
    },
  },
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}


function createNodes(permissions = {}) {
  return useProductionNodes({
    canManageNodes: ref(permissions.nodes ?? true),
    canManageCapabilities: ref(permissions.capabilities ?? true),
    canManageCalendars: ref(permissions.calendars ?? true),
  })
}


describe('useProductionNodes', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mocks.listProductionNodes.mockResolvedValue({
      nodes: [
        { id: 11, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01', calendar_id: 1, row_version: 2 },
        { id: 12, process_id: 7, process_name: '焊接', node_code: 'WELD-02', node_name: '焊接-02', calendar_id: 1, row_version: 1 },
        { id: 21, process_id: 8, process_name: '打磨', node_code: 'GRIND-01', node_name: '打磨-01', calendar_id: 1, row_version: 1 },
      ],
    })
    mocks.listScheduleCalendars.mockResolvedValue({ calendars: [{ id: 1, calendar_name: '九小时工作制' }] })
    mocks.createProductionNode.mockResolvedValue({ id: 22 })
    mocks.updateProductionNode.mockResolvedValue({ id: 11, row_version: 3 })
    mocks.listProductionNodeCapabilities.mockResolvedValue({ capabilities: [] })
    mocks.replaceProductionNodeCapabilities.mockResolvedValue({ capabilities: [] })
    mocks.createProductionNodeOverride.mockResolvedValue({ id: 31 })
  })

  it('loads and groups stable production nodes without using a production-line directory', async () => {
    const nodes = createNodes()
    await nodes.loadNodes()

    expect(mocks.listProductionNodes).toHaveBeenCalledWith({ limit: 500 })
    expect(nodes.nodesByProcess.value).toEqual([
      expect.objectContaining({ process_id: 7, process_name: '焊接', nodes: expect.arrayContaining([
        expect.objectContaining({ node_code: 'WELD-01' }),
        expect.objectContaining({ node_code: 'WELD-02' }),
      ]) }),
      expect.objectContaining({ process_id: 8, process_name: '打磨' }),
    ])
    expect(nodes.productionCalendars.value).toEqual([{ id: 1, calendar_name: '九小时工作制' }])
  })

  it('enforces granular node permissions before sending write commands', async () => {
    const nodes = createNodes({ nodes: false, capabilities: false, calendars: false })
    nodes.nodeForm.value = {
      process_id: 7,
      node_code: 'WELD-03',
      node_name: '焊接-03',
      capacity_mode: 'exclusive',
      status: 'active',
      calendar_id: 1,
      row_version: 1,
      reason: '扩充生产节点',
      idempotency_key: 'node-permission-test',
    }

    expect(await nodes.saveNode()).toBeNull()
    expect(await nodes.loadCapabilities({ id: 11 })).toBeNull()
    expect(await nodes.createCalendarOverride()).toBeNull()
    expect(mocks.createProductionNode).not.toHaveBeenCalled()
    expect(mocks.listProductionNodeCapabilities).not.toHaveBeenCalled()
    expect(mocks.createProductionNodeOverride).not.toHaveBeenCalled()
  })

  it('round-trips capability facts before replacing them and creates node calendar overrides', async () => {
    mocks.listProductionNodeCapabilities.mockResolvedValue({
      capabilities: [{
        product_id: 5,
        route_version_id: 71,
        process_version_id: 72,
        max_batch_quantity: 20,
        batch_minutes: 45,
        changeover_minutes: 10,
        allow_mixed_orders: false,
        status: 'active',
      }],
    })
    const nodes = createNodes()
    await nodes.loadNodes()
    await nodes.loadCapabilities(nodes.productionNodes.value[0])
    nodes.capabilityForm.value.reason = '限定精确产品和版本'
    await nodes.saveCapabilities()

    expect(mocks.replaceProductionNodeCapabilities).toHaveBeenCalledWith(11, expect.objectContaining({
      capabilities: [expect.objectContaining({
        product_id: 5,
        route_version_id: 71,
        process_version_id: 72,
      })],
      reason: '限定精确产品和版本',
    }))

    nodes.prepareOverride(nodes.productionNodes.value[0])
    nodes.overrideForm.value.start_at = '2026-09-20T08:00'
    nodes.overrideForm.value.end_at = '2026-09-20T12:00'
    nodes.overrideForm.value.reason = '计划检修'
    await nodes.createCalendarOverride()

    expect(mocks.createProductionNodeOverride).toHaveBeenCalledWith(11, expect.objectContaining({
      override_type: 'unavailable',
      reason: '计划检修',
    }))
  })

  it('refreshes the selected node override list after a successful create', async () => {
    mocks.listProductionNodeOverrides
      .mockResolvedValueOnce({ overrides: [{ id: 81, production_node_id: 11, reason: '旧例外' }] })
      .mockResolvedValueOnce({ overrides: [{ id: 91, production_node_id: 11, reason: '新建检修' }] })
    const nodes = createNodes()
    await nodes.loadNodes()
    const selectedNode = nodes.productionNodes.value[0]
    nodes.prepareOverride(selectedNode)
    await nodes.loadOverrides(selectedNode)
    nodes.overrideForm.value.start_at = '2026-09-21T08:00'
    nodes.overrideForm.value.end_at = '2026-09-21T12:00'
    nodes.overrideForm.value.reason = '新建检修'

    await nodes.createCalendarOverride()

    expect(mocks.listProductionNodeOverrides).toHaveBeenCalledTimes(2)
    expect(mocks.listProductionNodeOverrides).toHaveBeenLastCalledWith(11, { limit: 200 })
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 91, production_node_id: 11, reason: '新建检修' }),
    ])
  })

  it('does not let a stale create completion overwrite the current override context', async () => {
    const pendingCreate = deferred()
    mocks.createProductionNodeOverride
      .mockReturnValueOnce(pendingCreate.promise)
      .mockResolvedValueOnce({ id: 92 })
    mocks.listProductionNodeOverrides
      .mockResolvedValueOnce({ overrides: [{ id: 81, production_node_id: 11, reason: 'A 初始' }] })
      .mockResolvedValueOnce({ overrides: [{ id: 82, production_node_id: 12, reason: 'B 当前' }] })
      .mockResolvedValueOnce({ overrides: [{ id: 92, production_node_id: 12, reason: 'B 新建' }] })
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    nodes.prepareOverride(nodeA)
    await nodes.loadOverrides(nodeA)
    nodes.overrideForm.value.start_at = '2026-09-21T08:00'
    nodes.overrideForm.value.end_at = '2026-09-21T12:00'
    nodes.overrideForm.value.reason = 'A 慢请求'

    const creatingA = nodes.createCalendarOverride()
    nodes.prepareOverride(nodeB)
    await nodes.loadOverrides(nodeB)
    pendingCreate.resolve({ id: 91 })
    await creatingA

    expect(nodes.overrideForm.value.production_node_id).toBe(12)
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 82, production_node_id: 12, reason: 'B 当前' }),
    ])
    expect(mocks.listProductionNodeOverrides).toHaveBeenCalledTimes(2)

    nodes.overrideForm.value.start_at = '2026-09-21T13:00'
    nodes.overrideForm.value.end_at = '2026-09-21T17:00'
    nodes.overrideForm.value.reason = 'B 新建'
    await nodes.createCalendarOverride()

    expect(mocks.createProductionNodeOverride).toHaveBeenLastCalledWith(12, expect.objectContaining({
      reason: 'B 新建',
    }))
    expect(nodes.overrideForm.value.production_node_id).toBe(12)
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 92, production_node_id: 12, reason: 'B 新建' }),
    ])
  })

  it('keeps node load errors in node state and allows retry', async () => {
    mocks.listProductionNodes
      .mockRejectedValueOnce(new Error('节点目录不可用'))
      .mockResolvedValueOnce({ nodes: [] })
    const nodes = createNodes()

    await nodes.loadNodes()
    expect(nodes.nodesError.value).toBe('节点目录不可用')

    await nodes.loadNodes()
    expect(nodes.nodesError.value).toBe('')
  })

  it('loads and cancels calendar overrides for the selected node', async () => {
    mocks.listProductionNodeOverrides.mockResolvedValue({
      overrides: [{ id: 81, production_node_id: 11, status: 'active' }],
    })
    mocks.cancelProductionNodeOverride.mockResolvedValue({ id: 81, status: 'cancelled' })
    const nodes = createNodes()

    await nodes.loadOverrides({ id: 11 })
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 81, production_node_id: 11 }),
    ])

    await nodes.cancelOverride({ id: 81, production_node_id: 11 })
    expect(mocks.cancelProductionNodeOverride).toHaveBeenCalledWith(
      81,
      expect.objectContaining({ reason: expect.any(String), idempotency_key: expect.any(String) }),
    )
  })

  it('ignores a stale capability response after the selected node changes', async () => {
    let resolveFirst
    mocks.listProductionNodeCapabilities
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'CURRENT' }] })
    const nodes = createNodes()

    const first = nodes.loadCapabilities({ id: 11, node_code: 'A' })
    await nodes.loadCapabilities({ id: 12, node_code: 'B' })
    resolveFirst({ capabilities: [{ product_family: 'STALE' }] })
    await first

    expect(nodes.capabilityForm.value.production_node_id).toBe(12)
    expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('CURRENT')
  })

  it('does not refresh a saved capability into a node selected while the save was pending', async () => {
    const pendingSave = deferred()
    mocks.listProductionNodeCapabilities
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 初始' }] })
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'B 当前' }] })
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 错误刷新' }] })
    mocks.replaceProductionNodeCapabilities.mockReturnValueOnce(pendingSave.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    await nodes.loadCapabilities(nodeA)
    nodes.capabilityForm.value.reason = 'A 慢请求'

    const savingA = nodes.saveCapabilities()
    await nodes.loadCapabilities(nodeB)
    pendingSave.resolve({ capabilities: [] })
    await savingA

    expect(nodes.capabilityForm.value.production_node_id).toBe(12)
    expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('B 当前')
    expect(mocks.listProductionNodeCapabilities).toHaveBeenCalledTimes(2)
  })

  it('ignores stale calendar overrides after the selected node changes', async () => {
    let resolveFirst
    mocks.listProductionNodeOverrides
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ overrides: [{ id: 82, production_node_id: 12 }] })
    const nodes = createNodes()

    const first = nodes.loadOverrides({ id: 11 })
    await nodes.loadOverrides({ id: 12 })
    resolveFirst({ overrides: [{ id: 81, production_node_id: 11 }] })
    await first

    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 82, production_node_id: 12 }),
    ])
  })

  it('exposes grouped manager state, permissions, and actions with shared identity', () => {
    const nodes = createNodes()

    expect(nodes.nodeManager.state.productionNodes).toBe(nodes.productionNodes)
    expect(nodes.nodeManager.state.nodesError).toBe(nodes.nodesError)
    expect(nodes.nodeManager.state.overrideSaving).toBe(nodes.overrideSaving)
    expect(nodes.nodeManager.state.capabilitySaving).toBe(nodes.capabilitySaving)
    expect(nodes.nodeManager.permissions.canManageNodes.value).toBe(true)
    expect(nodes.nodeManager.permissions.canManageCapabilities.value).toBe(true)
    expect(nodes.nodeManager.permissions.canManageCalendars.value).toBe(true)
    expect(nodes.nodeManager.actions.loadNodes).toBe(nodes.loadNodes)
    expect(nodes.nodeManager.actions.cancelOverride).toBe(nodes.cancelOverride)
    expect(nodes.nodeManager.actions.saveCapabilities).toBe(nodes.saveCapabilities)
  })

  it('blocks duplicate node saves while exposing saving state', async () => {
    const pending = deferred()
    mocks.createProductionNode.mockReturnValueOnce(pending.promise)
    const nodes = createNodes()
    nodes.nodeForm.value = {
      process_id: 7,
      node_code: 'WELD-03',
      node_name: '焊接-03',
      capacity_mode: 'exclusive',
      status: 'active',
      calendar_id: 1,
      row_version: 1,
      reason: '扩充生产节点',
      idempotency_key: 'node-duplicate-test',
    }

    const first = nodes.saveNode()
    expect(nodes.nodeSaving.value).toBe(true)
    expect(await nodes.saveNode()).toBeNull()
    expect(mocks.createProductionNode).toHaveBeenCalledTimes(1)
    pending.resolve({ id: 22 })
    await first
    expect(nodes.nodeSaving.value).toBe(false)
  })

  it('blocks duplicate capability saves while exposing saving state', async () => {
    const pending = deferred()
    mocks.replaceProductionNodeCapabilities.mockReturnValueOnce(pending.promise)
    const nodes = createNodes()
    nodes.capabilityForm.value = {
      production_node_id: 11,
      node_label: 'WELD-01',
      capabilities: [],
      reason: '更新能力',
      idempotency_key: 'capability-duplicate-test',
    }

    const first = nodes.saveCapabilities()
    expect(nodes.capabilitySaving.value).toBe(true)
    expect(await nodes.saveCapabilities()).toBeNull()
    expect(mocks.replaceProductionNodeCapabilities).toHaveBeenCalledTimes(1)
    pending.resolve({ capabilities: [] })
    await first
    expect(nodes.capabilitySaving.value).toBe(false)
  })

  it('blocks duplicate override creation while exposing saving state', async () => {
    const pending = deferred()
    mocks.createProductionNodeOverride.mockReturnValueOnce(pending.promise)
    const nodes = createNodes()
    nodes.overrideForm.value = {
      production_node_id: 11,
      start_at: '2026-09-20T08:00',
      end_at: '2026-09-20T12:00',
      override_type: 'unavailable',
      reason: '计划检修',
      idempotency_key: 'override-duplicate-test',
    }

    const first = nodes.createCalendarOverride()
    expect(nodes.overrideSaving.value).toBe(true)
    expect(await nodes.createCalendarOverride()).toBeNull()
    expect(mocks.createProductionNodeOverride).toHaveBeenCalledTimes(1)
    pending.resolve({ id: 31 })
    await first
    expect(nodes.overrideSaving.value).toBe(false)
  })

  it('blocks duplicate override cancellation while exposing saving state', async () => {
    const pending = deferred()
    mocks.cancelProductionNodeOverride.mockReturnValueOnce(pending.promise)
    const nodes = createNodes()

    const first = nodes.cancelOverride({ id: 81, production_node_id: 11 })
    expect(nodes.overrideSaving.value).toBe(true)
    expect(await nodes.cancelOverride({ id: 81, production_node_id: 11 })).toBeNull()
    expect(mocks.cancelProductionNodeOverride).toHaveBeenCalledTimes(1)
    pending.resolve({ id: 81, status: 'cancelled' })
    await first
    expect(nodes.overrideSaving.value).toBe(false)
  })

  it('keeps cancellation errors local and resets saving state', async () => {
    mocks.cancelProductionNodeOverride.mockRejectedValueOnce(new Error('取消失败'))
    const nodes = createNodes()

    expect(await nodes.cancelOverride({ id: 81, production_node_id: 11 })).toBeNull()
    expect(nodes.overridesError.value).toBe('取消失败')
    expect(nodes.overrideSaving.value).toBe(false)
    expect(mocks.showToast).toHaveBeenCalledWith('取消失败', 'error')
  })

  it('does not refresh a cancelled node after override selection moves elsewhere', async () => {
    const cancellation = deferred()
    mocks.listProductionNodeOverrides
      .mockResolvedValueOnce({ overrides: [{ id: 81, production_node_id: 11 }] })
      .mockResolvedValueOnce({ overrides: [{ id: 82, production_node_id: 12 }] })
      .mockResolvedValueOnce({ overrides: [{ id: 83, production_node_id: 11 }] })
    mocks.cancelProductionNodeOverride.mockReturnValueOnce(cancellation.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    await nodes.loadOverrides({ id: 11 })

    const cancelling = nodes.cancelOverride({ id: 81, production_node_id: 11 })
    await nodes.loadOverrides({ id: 12 })
    cancellation.resolve({ id: 81, status: 'cancelled' })
    await cancelling

    expect(mocks.listProductionNodeOverrides).toHaveBeenCalledTimes(2)
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 82, production_node_id: 12 }),
    ])
  })
})
