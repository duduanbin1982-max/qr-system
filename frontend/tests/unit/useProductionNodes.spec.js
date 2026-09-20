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
    canViewNodes: ref(permissions.view ?? true),
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

  it('keeps the permitted node directory when the separate schedule-calendar read is denied', async () => {
    mocks.listScheduleCalendars.mockRejectedValueOnce(new Error('无权限'))
    const nodes = createNodes({ view: true, nodes: false, capabilities: false, calendars: false })

    const result = await nodes.loadNodes()

    expect(result?.nodes).toHaveLength(3)
    expect(nodes.productionNodes.value).toHaveLength(3)
    expect(nodes.productionCalendars.value).toEqual([])
    expect(nodes.nodesError.value).toBe('')
    expect(nodes.calendarsError.value).toBe('无权限')
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it('does not load the calendar catalog without node view permission', async () => {
    const nodes = createNodes({ view: false })

    expect(await nodes.loadCalendars()).toBeNull()
    expect(mocks.listScheduleCalendars).not.toHaveBeenCalled()
    expect(nodes.calendarsLoading.value).toBe(false)
  })

  it('publishes the node directory before a slow calendar catalog settles', async () => {
    const pendingCalendars = deferred()
    mocks.listScheduleCalendars.mockReturnValueOnce(pendingCalendars.promise)
    const nodes = createNodes()
    const loading = nodes.loadNodes()

    await Promise.resolve()
    await Promise.resolve()

    expect(nodes.productionNodes.value).toHaveLength(3)
    expect(nodes.nodesLoading.value).toBe(false)
    expect(nodes.calendarsLoading.value).toBe(true)

    pendingCalendars.resolve({ calendars: [{ id: 1, calendar_name: '九小时工作制' }] })
    await loading
    expect(nodes.calendarsLoading.value).toBe(false)
  })

  it('records an independent calendar result when the node directory fails', async () => {
    mocks.listProductionNodes.mockRejectedValueOnce(new Error('节点目录失败'))
    mocks.listScheduleCalendars.mockResolvedValueOnce({
      calendars: [{ id: 2, calendar_name: '备用日历' }],
    })
    const nodes = createNodes()

    expect(await nodes.loadNodes()).toBeNull()

    expect(nodes.nodesError.value).toBe('节点目录失败')
    expect(nodes.productionCalendars.value).toEqual([{ id: 2, calendar_name: '备用日历' }])
    expect(nodes.calendarsError.value).toBe('')
    expect(nodes.calendarsLoading.value).toBe(false)
  })

  it('retains an independent calendar failure when the node directory also fails', async () => {
    mocks.listProductionNodes.mockRejectedValueOnce(new Error('节点目录失败'))
    mocks.listScheduleCalendars.mockRejectedValueOnce(new Error('日历目录失败'))
    const nodes = createNodes()

    expect(await nodes.loadNodes()).toBeNull()

    expect(nodes.nodesError.value).toBe('节点目录失败')
    expect(nodes.calendarsError.value).toBe('日历目录失败')
    expect(nodes.calendarsLoading.value).toBe(false)
  })

  it('exposes calendar loading independently for the editor state', async () => {
    const calendars = deferred()
    mocks.listScheduleCalendars.mockReturnValueOnce(calendars.promise)
    const nodes = createNodes()

    const loading = nodes.loadNodes()
    expect(nodes.calendarsLoading.value).toBe(true)
    calendars.resolve({ calendars: [{ id: 1, calendar_name: '九小时工作制' }] })
    await loading

    expect(nodes.calendarsLoading.value).toBe(false)
    expect(nodes.calendarsError.value).toBe('')
  })

  it('keeps only the latest overlapping node directory response authoritative', async () => {
    const olderNodes = deferred()
    const olderCalendars = deferred()
    const newerNodes = deferred()
    const newerCalendars = deferred()
    mocks.listProductionNodes
      .mockReset()
      .mockReturnValueOnce(olderNodes.promise)
      .mockReturnValueOnce(newerNodes.promise)
    mocks.listScheduleCalendars
      .mockReset()
      .mockReturnValueOnce(olderCalendars.promise)
      .mockReturnValueOnce(newerCalendars.promise)
    const nodes = createNodes()

    const older = nodes.loadNodes()
    const newer = nodes.loadNodes()
    olderNodes.resolve({ nodes: [{ id: 11, node_code: 'STALE' }] })
    olderCalendars.resolve({ calendars: [{ id: 1, calendar_name: '旧日历' }] })
    await older

    expect(nodes.nodesLoading.value).toBe(true)
    expect(nodes.productionNodes.value).toEqual([])

    newerNodes.resolve({ nodes: [{ id: 12, node_code: 'CURRENT' }] })
    newerCalendars.resolve({ calendars: [{ id: 2, calendar_name: '当前日历' }] })
    await newer

    expect(nodes.nodesLoading.value).toBe(false)
    expect(nodes.nodesError.value).toBe('')
    expect(nodes.productionNodes.value).toEqual([{ id: 12, node_code: 'CURRENT' }])
    expect(nodes.productionCalendars.value).toEqual([{ id: 2, calendar_name: '当前日历' }])
  })

  it('ignores an older node-directory failure after a newer request succeeds', async () => {
    const olderNodes = deferred()
    const olderCalendars = deferred()
    mocks.listProductionNodes
      .mockReset()
      .mockReturnValueOnce(olderNodes.promise)
      .mockResolvedValueOnce({ nodes: [{ id: 12, node_code: 'CURRENT' }] })
    mocks.listScheduleCalendars
      .mockReset()
      .mockReturnValueOnce(olderCalendars.promise)
      .mockResolvedValueOnce({ calendars: [{ id: 2, calendar_name: '当前日历' }] })
    const nodes = createNodes()

    const older = nodes.loadNodes()
    await nodes.loadNodes()
    olderCalendars.resolve({ calendars: [{ id: 1, calendar_name: '旧日历' }] })
    olderNodes.reject(new Error('旧目录失败'))
    await older

    expect(nodes.nodesLoading.value).toBe(false)
    expect(nodes.nodesError.value).toBe('')
    expect(nodes.productionNodes.value).toEqual([{ id: 12, node_code: 'CURRENT' }])
    expect(nodes.productionCalendars.value).toEqual([{ id: 2, calendar_name: '当前日历' }])
  })

  it('loads calendar data with view permission even without calendar write permission', async () => {
    mocks.listProductionNodeOverrides.mockResolvedValueOnce({
      overrides: [{ id: 81, production_node_id: 11, status: 'active' }],
    })
    const nodes = createNodes({ calendars: false, view: true })
    const node = { id: 11, node_code: 'WELD-01', node_name: '焊接-01' }

    nodes.selectNodeContext(node)
    const result = await nodes.loadOverrides(node)

    expect(result).toEqual({
      overrides: [{ id: 81, production_node_id: 11, status: 'active' }],
    })
    expect(mocks.listProductionNodeOverrides).toHaveBeenCalledWith(11, { limit: 200 })
  })

  it('loads bare-array calendar overrides into the selected-node detail state', async () => {
    const overrides = [{
      id: 91,
      production_node_id: 11,
      start_at: '2099-01-01T08:00:00',
      end_at: '2099-01-01T12:00:00',
      status: 'active',
    }]
    mocks.listProductionNodeOverrides.mockResolvedValueOnce(overrides)
    const nodes = createNodes()
    const node = { id: 11, node_code: 'WELD-01', node_name: '焊接-01' }
    nodes.selectNodeContext(node)

    const result = await nodes.loadOverrides(node)

    expect(result).toEqual(overrides)
    expect(nodes.nodeOverrides.value).toEqual(overrides)
    expect(nodes.nodeSummary.value.future_override_count).toBe(1)
  })

  it('counts future overrides from a bare-array summary response', async () => {
    mocks.listProductionNodeCapabilities.mockResolvedValueOnce({ capabilities: [] })
    mocks.listProductionNodeOverrides.mockResolvedValueOnce([{
      id: 92,
      production_node_id: 11,
      end_at: '2099-01-02T12:00:00',
      status: 'active',
    }])
    const nodes = createNodes()
    const node = { id: 11, node_code: 'WELD-01', node_name: '焊接-01' }
    nodes.selectNodeContext(node)

    await nodes.loadNodeSummary(node)

    expect(nodes.nodeSummary.value.future_override_count).toBe(1)
  })

  it('clears detail contexts and blocks stale writes after the current node becomes null', async () => {
    mocks.listProductionNodeCapabilities.mockResolvedValueOnce({ capabilities: [] })
    const nodes = createNodes()
    const nodeA = { id: 11, node_code: 'WELD-01', node_name: '焊接-01' }
    nodes.selectNodeContext(nodeA)
    nodes.prepareOverride(nodeA)
    await nodes.loadCapabilities(nodeA)
    nodes.overrideForm.value = {
      production_node_id: 11,
      start_at: '2026-09-20T08:00',
      end_at: '2026-09-20T12:00',
      override_type: 'maintenance',
      reason: '旧节点例外',
      idempotency_key: 'override-stale-node-a',
    }
    nodes.capabilityForm.value.reason = '旧节点能力'

    nodes.selectNodeContext(null)
    await nodes.loadNodes()

    expect(nodes.currentNodeId.value).toBeNull()
    expect(nodes.overrideForm.value.production_node_id).toBe('')
    expect(nodes.capabilityForm.value.production_node_id).toBe('')
    expect(await nodes.createCalendarOverride()).toBeNull()
    expect(await nodes.saveCapabilities()).toBeNull()
    expect(mocks.createProductionNodeOverride).not.toHaveBeenCalled()
    expect(mocks.replaceProductionNodeCapabilities).not.toHaveBeenCalled()
  })

  it('loads a real selected-node summary with capability and future override counts', async () => {
    mocks.listProductionNodeCapabilities.mockResolvedValueOnce({
      capabilities: [{ id: 1 }, { id: 2 }],
    })
    mocks.listProductionNodeOverrides.mockResolvedValueOnce({
      overrides: [
        { id: 81, end_at: '2099-01-01T12:00:00', status: 'active' },
        { id: 82, end_at: '2099-01-02T12:00:00', status: 'cancelled' },
        { id: 83, end_at: '2000-01-01T12:00:00', status: 'active' },
      ],
    })
    const nodes = createNodes()
    const node = { id: 11, node_code: 'WELD-01', node_name: '焊接-01', capacity_minutes: 540 }
    nodes.selectNodeContext(node)

    await nodes.loadNodeSummary(node)

    expect(nodes.nodeSummary.value).toMatchObject({
      production_node_id: 11,
      capability_count: 2,
      future_override_count: 1,
    })
  })

  it('ignores a stale selected-node summary after the context moves to another node', async () => {
    const capabilityA = deferred()
    const overridesA = deferred()
    mocks.listProductionNodeCapabilities
      .mockReturnValueOnce(capabilityA.promise)
      .mockResolvedValueOnce({ capabilities: [{ id: 2 }] })
    mocks.listProductionNodeOverrides
      .mockReturnValueOnce(overridesA.promise)
      .mockResolvedValueOnce({
        overrides: [{ id: 82, end_at: '2099-01-02T12:00:00', status: 'active' }],
      })
    const nodes = createNodes()
    const nodeA = { id: 11, node_code: 'A' }
    const nodeB = { id: 12, node_code: 'B' }
    nodes.selectNodeContext(nodeA)
    const loadingA = nodes.loadNodeSummary(nodeA)

    nodes.selectNodeContext(nodeB)
    await nodes.loadNodeSummary(nodeB)
    capabilityA.resolve({ capabilities: [{ id: 1 }, { id: 3 }] })
    overridesA.resolve({
      overrides: [
        { id: 81, end_at: '2099-01-01T12:00:00', status: 'active' },
        { id: 83, end_at: '2099-01-03T12:00:00', status: 'active' },
      ],
    })
    await loadingA

    expect(nodes.nodeSummary.value).toMatchObject({
      production_node_id: 12,
      capability_count: 1,
      future_override_count: 1,
    })
  })

  it('does not let a late summary overwrite newer same-node detail counts', async () => {
    const pendingSummaryCapabilities = deferred()
    const pendingSummaryOverrides = deferred()
    mocks.listProductionNodeCapabilities
      .mockReturnValueOnce(pendingSummaryCapabilities.promise)
      .mockResolvedValueOnce({ capabilities: [{ id: 1 }, { id: 2 }, { id: 3 }] })
    mocks.listProductionNodeOverrides
      .mockReturnValueOnce(pendingSummaryOverrides.promise)
      .mockResolvedValueOnce({
        overrides: [
          { id: 91, end_at: '2099-01-01T12:00:00', status: 'active' },
          { id: 92, end_at: '2099-01-02T12:00:00', status: 'active' },
        ],
      })
    const nodes = createNodes()
    const nodeA = { id: 11, node_code: 'A', node_name: '节点 A' }
    nodes.selectNodeContext(nodeA)

    const loadingSummary = nodes.loadNodeSummary(nodeA)
    await nodes.loadCapabilities(nodeA)
    await nodes.loadOverrides(nodeA)
    pendingSummaryCapabilities.resolve({ capabilities: [{ id: 99 }] })
    pendingSummaryOverrides.resolve({
      overrides: [{ id: 99, end_at: '2099-01-03T12:00:00', status: 'active' }],
    })
    await loadingSummary

    expect(nodes.nodeSummary.value).toMatchObject({
      production_node_id: 11,
      capability_count: 3,
      future_override_count: 2,
    })
  })

  it('does not surface a stale summary error after newer same-node details succeed', async () => {
    const pendingSummaryCapabilities = deferred()
    const pendingSummaryOverrides = deferred()
    mocks.listProductionNodeCapabilities
      .mockReturnValueOnce(pendingSummaryCapabilities.promise)
      .mockResolvedValueOnce({ capabilities: [{ id: 1 }, { id: 2 }] })
    mocks.listProductionNodeOverrides
      .mockReturnValueOnce(pendingSummaryOverrides.promise)
      .mockResolvedValueOnce({
        overrides: [{ id: 91, end_at: '2099-01-01T12:00:00', status: 'active' }],
      })
    const nodes = createNodes()
    const nodeA = { id: 11, node_code: 'A', node_name: '节点 A' }
    nodes.selectNodeContext(nodeA)

    const loadingSummary = nodes.loadNodeSummary(nodeA)
    await nodes.loadCapabilities(nodeA)
    await nodes.loadOverrides(nodeA)
    pendingSummaryOverrides.resolve({ overrides: [] })
    pendingSummaryCapabilities.reject(new Error('旧摘要失败'))
    await loadingSummary

    expect(nodes.nodeSummaryError.value).toBe('')
    expect(nodes.nodeSummary.value).toMatchObject({
      capability_count: 2,
      future_override_count: 1,
    })
  })

  it('enforces granular node permissions before sending write commands', async () => {
    mocks.listProductionNodeCapabilities.mockResolvedValueOnce({
      capabilities: [{ product_family: 'READ-ONLY' }],
    })
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
    expect(await nodes.loadCapabilities({ id: 11, node_code: 'WELD-01' })).toEqual({
      capabilities: [{ product_family: 'READ-ONLY' }],
    })
    expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('READ-ONLY')
    expect(await nodes.saveCapabilities()).toBeNull()
    expect(await nodes.createCalendarOverride()).toBeNull()
    expect(mocks.createProductionNode).not.toHaveBeenCalled()
    expect(mocks.listProductionNodeCapabilities).toHaveBeenCalledWith(11)
    expect(mocks.replaceProductionNodeCapabilities).not.toHaveBeenCalled()
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

  it('does not let a slow node A save replace node B edits', async () => {
    const pendingSave = deferred()
    mocks.updateProductionNode.mockReturnValueOnce(pendingSave.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    nodes.selectNodeContext(nodeA)
    nodes.editNode(nodeA)
    nodes.nodeForm.value.node_name = 'A 已编辑'
    nodes.nodeForm.value.reason = '保存 A'

    const savingA = nodes.saveNode()
    nodes.selectNodeContext(nodeB)
    nodes.editNode(nodeB)
    nodes.nodeForm.value.node_name = 'B 新编辑'
    const nodeBForm = nodes.nodeForm.value
    pendingSave.resolve({ ...nodeA, node_name: 'A 已保存', row_version: 3 })
    const result = await savingA

    expect(result).toBeNull()
    expect(nodes.currentNodeId.value).toBe(12)
    expect(nodes.nodeForm.value).toBe(nodeBForm)
    expect(nodes.nodeForm.value.node_name).toBe('B 新编辑')
    expect(nodes.productionNodes.value.find(node => node.id === 11)).toMatchObject({
      node_name: 'A 已保存',
      row_version: 3,
    })
    expect(mocks.listProductionNodes).toHaveBeenCalledTimes(1)
  })

  it('does not let an old A save replace a newer A context after an A to B to A cycle', async () => {
    const pendingSave = deferred()
    mocks.updateProductionNode.mockReturnValueOnce(pendingSave.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    nodes.selectNodeContext(nodeA)
    nodes.editNode(nodeA)
    nodes.nodeForm.value.node_name = 'A 旧编辑'
    nodes.nodeForm.value.reason = '保存 A 旧上下文'

    const oldSave = nodes.saveNode()
    nodes.selectNodeContext(nodeB)
    nodes.editNode(nodeB)
    nodes.selectNodeContext(nodeA)
    nodes.editNode(nodeA)
    nodes.nodeForm.value.node_name = 'A 新上下文编辑'
    const freshAForm = nodes.nodeForm.value
    pendingSave.resolve({ ...nodeA, node_name: 'A 已保存', row_version: 3 })
    const result = await oldSave

    expect(result).toBeNull()
    expect(nodes.currentNodeId.value).toBe(11)
    expect(nodes.nodeForm.value).toBe(freshAForm)
    expect(nodes.nodeForm.value.node_name).toBe('A 新上下文编辑')
    expect(nodes.productionNodes.value.find(node => node.id === 11)).toMatchObject({
      node_name: 'A 已保存',
      row_version: 3,
    })
    expect(mocks.listProductionNodes).toHaveBeenCalledTimes(1)
  })

  it('does not confirm a node save after selection changes during the trailing summary refresh', async () => {
    const summaryStarted = deferred()
    const pendingCapabilities = deferred()
    const pendingOverrides = deferred()
    mocks.updateProductionNode.mockResolvedValueOnce({
      id: 11,
      process_id: 7,
      process_name: '焊接',
      node_code: 'WELD-01',
      node_name: 'A 已保存',
      calendar_id: 1,
      row_version: 3,
    })
    mocks.listProductionNodeCapabilities.mockImplementationOnce(() => {
      summaryStarted.resolve()
      return pendingCapabilities.promise
    })
    mocks.listProductionNodeOverrides.mockReturnValueOnce(pendingOverrides.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    nodes.selectNodeContext(nodeA)
    nodes.editNode(nodeA)
    nodes.nodeForm.value.node_name = 'A 已编辑'
    nodes.nodeForm.value.reason = '保存 A'

    const savingA = nodes.saveNode()
    await summaryStarted.promise
    nodes.selectNodeContext(nodeB)
    nodes.editNode(nodeB)
    nodes.nodeForm.value.node_name = 'B 新编辑'
    const nodeBForm = nodes.nodeForm.value
    pendingCapabilities.resolve({ capabilities: [] })
    pendingOverrides.resolve({ overrides: [] })
    const result = await savingA

    expect(result).toBeNull()
    expect(nodes.currentNodeId.value).toBe(12)
    expect(nodes.nodeForm.value).toBe(nodeBForm)
    expect(nodes.nodeForm.value.node_name).toBe('B 新编辑')
    expect(mocks.showToast).not.toHaveBeenCalledWith('生产节点已更新')
  })

  it('preserves node input and dirty context when the post-save directory refresh fails', async () => {
    mocks.listProductionNodes
      .mockResolvedValueOnce({
        nodes: [{
          id: 11,
          process_id: 7,
          process_name: '焊接',
          node_code: 'WELD-01',
          node_name: '焊接-01',
          calendar_id: 1,
          row_version: 2,
        }],
      })
      .mockRejectedValueOnce(new Error('保存后刷新节点失败'))
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    nodes.selectNodeContext(nodeA)
    nodes.editNode(nodeA)
    nodes.nodeForm.value.node_name = '必须保留的节点名称'
    nodes.nodeForm.value.reason = '更新节点'
    const editedForm = nodes.nodeForm.value

    const result = await nodes.saveNode()

    expect(result).toBeNull()
    expect(nodes.nodeForm.value).toBe(editedForm)
    expect(nodes.nodeForm.value.node_name).toBe('必须保留的节点名称')
    expect(nodes.nodeForm.value.reason).toBe('更新节点')
    expect(nodes.nodesError.value).toBe('保存后刷新节点失败')
    expect(nodes.productionNodes.value).toEqual([expect.objectContaining({ id: 11, node_code: 'WELD-01' })])
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

  it('establishes an empty node B capability context before loading and keeps it after failure', async () => {
    const pendingB = deferred()
    mocks.listProductionNodeCapabilities
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A ONLY' }] })
      .mockReturnValueOnce(pendingB.promise)
    const nodes = createNodes()
    const nodeA = { id: 11, node_code: 'A', node_name: '节点 A' }
    const nodeB = { id: 12, node_code: 'B', node_name: '节点 B' }
    await nodes.loadCapabilities(nodeA)

    const loadingB = nodes.loadCapabilities(nodeB)
    expect(nodes.capabilityForm.value).toMatchObject({
      production_node_id: 12,
      node_label: 'B · 节点 B',
      capabilities: [],
    })
    expect(nodes.capabilitiesLoading.value).toBe(true)

    pendingB.reject(new Error('B 能力读取失败'))
    await loadingB

    expect(nodes.capabilityForm.value).toMatchObject({
      production_node_id: 12,
      node_label: 'B · 节点 B',
      capabilities: [],
    })
    expect(nodes.capabilitiesError.value).toBe('B 能力读取失败')
  })

  it('allows a same-node reload while saving and still confirms the post-save refresh', async () => {
    const pendingSave = deferred()
    mocks.listProductionNodeCapabilities
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 初始' }] })
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 同节点重载' }] })
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 已刷新' }] })
    mocks.replaceProductionNodeCapabilities.mockReturnValueOnce(pendingSave.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    await nodes.loadCapabilities(nodeA)
    nodes.capabilityForm.value.reason = 'A 更新'

    const savingA = nodes.saveCapabilities()
    await nodes.loadCapabilities(nodeA)
    pendingSave.resolve({ capabilities: [] })
    const result = await savingA

    expect(result).toEqual({ capabilities: [] })
    expect(mocks.listProductionNodeCapabilities).toHaveBeenCalledTimes(3)
    expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('A 已刷新')
    expect(nodes.capabilityForm.value.reason).toBe('')
  })

  it('returns failure and preserves the edited form when post-save refresh fails', async () => {
    mocks.listProductionNodeCapabilities
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 初始' }] })
      .mockRejectedValueOnce(new Error('保存后刷新失败'))
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    await nodes.loadCapabilities(nodeA)
    nodes.capabilityForm.value.capabilities[0].product_family = 'A 已编辑'
    nodes.capabilityForm.value.reason = '保留输入'
    const editedForm = nodes.capabilityForm.value

    const result = await nodes.saveCapabilities()

    expect(result).toBeNull()
    expect(nodes.capabilityForm.value).toBe(editedForm)
    expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('A 已编辑')
    expect(nodes.capabilityForm.value.reason).toBe('保留输入')
    expect(nodes.capabilitiesError.value).toBe('保存后刷新失败')
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
    const result = await savingA

    expect(result).toBeNull()
    expect(nodes.capabilityForm.value.production_node_id).toBe(12)
    expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('B 当前')
    expect(mocks.listProductionNodeCapabilities).toHaveBeenCalledTimes(2)
  })

  it('does not let an old A save confirm or refresh after an A to B to A context cycle', async () => {
    const pendingSave = deferred()
    mocks.listProductionNodeCapabilities
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 初始' }] })
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'B 当前' }] })
      .mockResolvedValueOnce({ capabilities: [{ product_family: 'A 新上下文' }] })
    mocks.replaceProductionNodeCapabilities.mockReturnValueOnce(pendingSave.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    await nodes.loadCapabilities(nodeA)
    nodes.capabilityForm.value.reason = 'A 旧保存'

    const oldSave = nodes.saveCapabilities()
    await nodes.loadCapabilities(nodeB)
    await nodes.loadCapabilities(nodeA)
    pendingSave.resolve({ capabilities: [] })
    const result = await oldSave

    expect(result).toBeNull()
    expect(nodes.capabilityForm.value.production_node_id).toBe(11)
    expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('A 新上下文')
    expect(mocks.listProductionNodeCapabilities).toHaveBeenCalledTimes(3)
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
    nodes.selectNodeContext({ id: 11, node_code: 'WELD-01', node_name: '焊接-01' })
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
    nodes.selectNodeContext({ id: 11, node_code: 'WELD-01', node_name: '焊接-01' })
    nodes.prepareOverride({ id: 11 })
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
    nodes.selectNodeContext({ id: 11, node_code: 'WELD-01', node_name: '焊接-01' })
    nodes.prepareOverride({ id: 11 })

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
    nodes.selectNodeContext({ id: 11, node_code: 'WELD-01', node_name: '焊接-01' })
    nodes.prepareOverride({ id: 11 })

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

  it('does not let a stale cancellation rejection hide the current node override list', async () => {
    const cancellation = deferred()
    mocks.listProductionNodeOverrides
      .mockResolvedValueOnce({ overrides: [{ id: 81, production_node_id: 11 }] })
      .mockResolvedValueOnce({ overrides: [{ id: 82, production_node_id: 12 }] })
    mocks.cancelProductionNodeOverride.mockReturnValueOnce(cancellation.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    nodes.selectNodeContext(nodeA)
    await nodes.loadOverrides(nodeA)

    const cancelling = nodes.cancelOverride({ id: 81, production_node_id: 11 })
    nodes.selectNodeContext(nodeB)
    await nodes.loadOverrides(nodeB)
    cancellation.reject(new Error('A 取消失败'))
    await cancelling

    expect(nodes.currentNodeId.value).toBe(12)
    expect(nodes.overridesError.value).toBe('')
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 82, production_node_id: 12 }),
    ])
  })

  it('does not let a cancelled request rejection overwrite a newer same-node reload', async () => {
    const cancellation = deferred()
    const newerLoad = deferred()
    mocks.listProductionNodeOverrides
      .mockResolvedValueOnce({ overrides: [{ id: 81, production_node_id: 11, status: 'active' }] })
      .mockReturnValueOnce(newerLoad.promise)
    mocks.cancelProductionNodeOverride.mockReturnValueOnce(cancellation.promise)
    const nodes = createNodes()
    const node = { id: 11, process_id: 7, node_code: 'WELD-01', node_name: '焊接-01' }
    nodes.selectNodeContext(node)
    nodes.prepareOverride(node)
    await nodes.loadOverrides(node)

    const cancelling = nodes.cancelOverride({ id: 81, production_node_id: 11, status: 'active' })
    expect(mocks.cancelProductionNodeOverride).toHaveBeenCalledOnce()
    nodes.prepareOverride(node)
    const reloading = nodes.loadOverrides(node)
    newerLoad.resolve({ overrides: [{ id: 82, production_node_id: 11, status: 'active' }] })
    await reloading
    cancellation.reject(new Error('旧取消失败'))
    await cancelling

    expect(nodes.overridesError.value).toBe('')
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 82, production_node_id: 11 }),
    ])
    expect(mocks.showToast).not.toHaveBeenCalledWith('旧取消失败', 'error')
  })

  it('counts only future active overrides in the node summary', async () => {
    mocks.listProductionNodeCapabilities.mockResolvedValueOnce({ capabilities: [] })
    mocks.listProductionNodeOverrides.mockResolvedValueOnce({
      overrides: [
        { id: 81, end_at: '2099-01-01T12:00:00', status: 'active' },
        { id: 82, end_at: '2099-01-02T12:00:00', status: 'completed' },
        { id: 83, end_at: '2099-01-03T12:00:00', status: 'expired' },
        { id: 84, end_at: '2099-01-04T12:00:00', status: 'cancelled' },
      ],
    })
    const nodes = createNodes()
    const node = { id: 11, process_id: 7, node_code: 'WELD-01', node_name: '焊接-01' }
    nodes.selectNodeContext(node)

    await nodes.loadNodeSummary(node)

    expect(nodes.nodeSummary.value.future_override_count).toBe(1)
  })

  it('rejects programmatic cancellation of completed or expired overrides', async () => {
    const nodes = createNodes()
    const node = { id: 11, process_id: 7, node_code: 'WELD-01', node_name: '焊接-01' }
    nodes.selectNodeContext(node)
    nodes.prepareOverride(node)

    expect(await nodes.cancelOverride({ id: 81, production_node_id: 11, status: 'completed' })).toBeNull()
    expect(await nodes.cancelOverride({ id: 82, production_node_id: 11, status: 'expired' })).toBeNull()
    expect(mocks.cancelProductionNodeOverride).not.toHaveBeenCalled()
  })

  it('does not let an old cancellation affect a newer A context after an A to B to A cycle', async () => {
    const cancellation = deferred()
    mocks.listProductionNodeOverrides
      .mockResolvedValueOnce({ overrides: [{ id: 81, production_node_id: 11, reason: 'A 旧上下文' }] })
      .mockResolvedValueOnce({ overrides: [{ id: 82, production_node_id: 12, reason: 'B 当前' }] })
      .mockResolvedValueOnce({ overrides: [{ id: 83, production_node_id: 11, reason: 'A 新上下文' }] })
    mocks.cancelProductionNodeOverride.mockReturnValueOnce(cancellation.promise)
    const nodes = createNodes()
    await nodes.loadNodes()
    const nodeA = nodes.productionNodes.value[0]
    const nodeB = nodes.productionNodes.value[1]
    nodes.selectNodeContext(nodeA)
    await nodes.loadOverrides(nodeA)

    const cancelling = nodes.cancelOverride({ id: 81, production_node_id: 11 })
    nodes.selectNodeContext(nodeB)
    await nodes.loadOverrides(nodeB)
    nodes.selectNodeContext(nodeA)
    await nodes.loadOverrides(nodeA)
    cancellation.reject(new Error('A 旧取消失败'))
    await cancelling

    expect(nodes.currentNodeId.value).toBe(11)
    expect(nodes.overridesError.value).toBe('')
    expect(nodes.nodeOverrides.value).toEqual([
      expect.objectContaining({ id: 83, production_node_id: 11, reason: 'A 新上下文' }),
    ])
    expect(mocks.listProductionNodeOverrides).toHaveBeenCalledTimes(3)
  })

  it('ignores a late override load after the current node is cleared', async () => {
    const pendingLoad = deferred()
    mocks.listProductionNodeOverrides.mockReturnValueOnce(pendingLoad.promise)
    const nodes = createNodes()
    const nodeA = { id: 11, node_code: 'A' }
    nodes.selectNodeContext(nodeA)

    const loading = nodes.loadOverrides(nodeA)
    nodes.selectNodeContext(null)
    pendingLoad.resolve({ overrides: [{ id: 81, production_node_id: 11 }] })
    await loading

    expect(nodes.currentNodeId.value).toBeNull()
    expect(nodes.nodeOverrides.value).toEqual([])
    expect(nodes.overridesError.value).toBe('')
  })
})
