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

vi.mock('@/lib/store.js', () => ({ showToast: vi.fn() }))


function createNodes(permissions = {}) {
  return useProductionNodes({
    canManageNodes: ref(permissions.nodes ?? true),
    canManageCapabilities: ref(permissions.capabilities ?? true),
    canManageCalendars: ref(permissions.calendars ?? true),
  })
}


describe('useProductionNodes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
})
