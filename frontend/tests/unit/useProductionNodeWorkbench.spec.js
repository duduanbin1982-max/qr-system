import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useProductionNodeWorkbench } from '@/composables/gantt/useProductionNodeWorkbench.js'

function createWorkbench() {
  return useProductionNodeWorkbench({
    nodes: ref([
      { id: 11, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01', status: 'active' },
      { id: 12, process_id: 7, process_name: '焊接', node_code: 'WELD-02', node_name: '焊接-02', status: 'maintenance' },
    ]),
    onEnterTab: vi.fn(),
    onSelectNode: vi.fn(),
    onClose: vi.fn(),
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
})
