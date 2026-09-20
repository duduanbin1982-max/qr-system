import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useProductionNodeWorkbench } from '@/composables/gantt/useProductionNodeWorkbench.js'

function createWorkbench(callbacks = {}) {
  return useProductionNodeWorkbench({
    nodes: ref([
      { id: 11, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01', status: 'active' },
      { id: 12, process_id: 7, process_name: '焊接', node_code: 'WELD-02', node_name: '焊接-02', status: 'maintenance' },
    ]),
    onEnterTab: callbacks.onEnterTab || vi.fn(),
    onSelectNode: callbacks.onSelectNode || vi.fn(),
    onClose: callbacks.onClose || vi.fn(),
  })
}

describe('useProductionNodeWorkbench', () => {
  it('filters nodes by query and status without changing the selected node', () => {
    const workbench = createWorkbench()
    workbench.selectedNodeId.value = 11
    workbench.search.value = '02'
    workbench.statusFilter.value = 'maintenance'

    expect(workbench.filteredGroups.value[0].nodes.map(node => node.id)).toEqual([12])
    expect(workbench.selectedNodeId.value).toBe(11)
  })

  it('guards tab, node, and close transitions while dirty', () => {
    const workbench = createWorkbench()
    workbench.markDirty(true)

    expect(workbench.requestTab('calendar')).toBe(false)
    expect(workbench.showDiscardConfirm.value).toBe(true)

    workbench.confirmDiscard()
    expect(workbench.activeTab.value).toBe('calendar')
    expect(workbench.isDirty.value).toBe(false)
  })

  it('defers a dirty node transition until discard is confirmed', () => {
    const onSelectNode = vi.fn()
    const workbench = createWorkbench({ onSelectNode })
    const targetNode = { id: 12, process_id: 7, process_name: '焊接' }
    workbench.selectedNodeId.value = 11
    workbench.markDirty(true)

    expect(workbench.requestNode(targetNode)).toBe(false)
    expect(workbench.selectedNodeId.value).toBe(11)
    expect(onSelectNode).not.toHaveBeenCalled()

    workbench.confirmDiscard()
    expect(workbench.selectedNodeId.value).toBe(12)
    expect(onSelectNode).toHaveBeenCalledOnce()
    expect(onSelectNode).toHaveBeenCalledWith(targetNode)
    expect(workbench.isDirty.value).toBe(false)
  })

  it('cancels a pending dirty node transition without changing selection', () => {
    const onSelectNode = vi.fn()
    const workbench = createWorkbench({ onSelectNode })
    const targetNode = { id: 12, process_id: 7, process_name: '焊接' }
    workbench.selectedNodeId.value = 11
    workbench.markDirty(true)

    expect(workbench.requestNode(targetNode)).toBe(false)
    workbench.cancelDiscard()

    expect(workbench.selectedNodeId.value).toBe(11)
    expect(onSelectNode).not.toHaveBeenCalled()
  })

  it('defers a dirty close transition until discard is confirmed', () => {
    const onClose = vi.fn()
    const workbench = createWorkbench({ onClose })
    workbench.markDirty(true)

    expect(workbench.requestClose()).toBe(false)
    expect(onClose).not.toHaveBeenCalled()

    workbench.confirmDiscard()
    expect(onClose).toHaveBeenCalledOnce()
    expect(workbench.isDirty.value).toBe(false)
  })

  it('cancels a pending dirty close transition without closing', () => {
    const onClose = vi.fn()
    const workbench = createWorkbench({ onClose })
    workbench.markDirty(true)

    expect(workbench.requestClose()).toBe(false)
    workbench.cancelDiscard()

    expect(onClose).not.toHaveBeenCalled()
  })
})
