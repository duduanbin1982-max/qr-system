import { computed, onBeforeUnmount, onMounted } from 'vue'

import { can } from '@/lib/auth.js'
import { useGanttBatch } from '@/composables/gantt/useGanttBatch.js'
import { useGanttData, isCompletedOrder } from '@/composables/gantt/useGanttData.js'
import { useGanttEditor } from '@/composables/gantt/useGanttEditor.js'
import { useGanttExport } from '@/composables/gantt/useGanttExport.js'
import { useProductionLines } from '@/composables/gantt/useProductionLines.js'


export function useGantt() {
  const canEdit = computed(() => can('schedule:edit'))
  const canManageLines = computed(() => can('settings:edit'))
  const lines = useProductionLines({ canManageLines })
  const data = useGanttData({ productionLines: lines.productionLines })

  function canAdjustOrder(order) {
    return canEdit.value && !isCompletedOrder(order)
  }

  const editor = useGanttEditor({
    dayWidth: data.dayWidth,
    ganttData: data.ganttData,
    barLeft: data.barLeft,
    canAdjustOrder,
    productionLines: lines.productionLines,
  })
  const batch = useGanttBatch({
    canEdit,
    canAdjustOrder,
    filteredOrders: data.filteredOrders,
    isCompleted: isCompletedOrder,
    reload: data.load,
  })
  const imageExport = useGanttExport()

  async function setScheduleScope(scope) {
    if (data.scheduleScope.value === scope) return
    batch.resetSelection()
    await data.setScheduleScope(scope)
  }

  function onKeyDown(event) {
    if (event.key === 'Escape') editor.undoLastDrag()
  }

  onMounted(() => {
    data.load()
    lines.loadLines()
    document.addEventListener('keydown', onKeyDown)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeyDown)
    editor.cleanup()
  })

  return {
    ...data,
    ...editor,
    ...lines,
    ...batch,
    ...imageExport,
    setScheduleScope,
    isCompleted: isCompletedOrder,
    canAdjustOrder,
    canEdit,
    canManageLines,
    onKeyDown,
  }
}
