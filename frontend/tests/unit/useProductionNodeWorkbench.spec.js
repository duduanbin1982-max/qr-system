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
    onDiscard: callbacks.onDiscard || vi.fn(),
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

  it('does not guard a click on the already-active tab', () => {
    const onEnterTab = vi.fn()
    const workbench = createWorkbench({ onEnterTab })
    workbench.activeTab.value = 'editor'
    workbench.markDirty(true)

    expect(workbench.requestTab('editor')).toBe(true)
    expect(workbench.showDiscardConfirm.value).toBe(false)
    expect(workbench.isDirty.value).toBe(true)
    expect(onEnterTab).not.toHaveBeenCalled()
  })

  it('defers a custom transition while dirty and discards or preserves it explicitly', () => {
    const transition = vi.fn()
    const workbench = createWorkbench()
    workbench.markDirty(true)

    expect(workbench.requestTransition(transition)).toBe(false)
    expect(transition).not.toHaveBeenCalled()

    workbench.cancelDiscard()
    expect(transition).not.toHaveBeenCalled()
    expect(workbench.isDirty.value).toBe(true)

    expect(workbench.requestTransition(transition)).toBe(false)
    workbench.confirmDiscard()
    expect(transition).toHaveBeenCalledOnce()
    expect(workbench.isDirty.value).toBe(false)
  })

  it('rolls back the active context before running a confirmed transition', async () => {
    const calls = []
    const workbench = createWorkbench({
      onDiscard: vi.fn(() => calls.push('rollback')),
    })
    workbench.selectedNodeId.value = 11
    workbench.activeTab.value = 'editor'
    workbench.markDirty(true)
    workbench.requestTransition(() => calls.push('transition'))

    await workbench.confirmDiscard()

    expect(calls).toEqual(['rollback', 'transition'])
    expect(workbench.isDirty.value).toBe(false)
  })

  it('resets tab, selection, filters, dirty state, and pending transitions for a new session', () => {
    const workbench = createWorkbench()
    workbench.activeTab.value = 'capabilities'
    workbench.selectedNodeId.value = 12
    workbench.search.value = 'WELD'
    workbench.statusFilter.value = 'maintenance'
    workbench.markDirty(true)
    workbench.requestClose()

    workbench.resetSession()

    expect(workbench.activeTab.value).toBe('list')
    expect(workbench.selectedNodeId.value).toBeNull()
    expect(workbench.search.value).toBe('')
    expect(workbench.statusFilter.value).toBe('')
    expect(workbench.isDirty.value).toBe(false)
    expect(workbench.showDiscardConfirm.value).toBe(false)
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
