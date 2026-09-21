import { computed, onBeforeUnmount, onMounted } from 'vue'

import { can } from '@/lib/auth.js'
import { useGanttBatch } from '@/composables/gantt/useGanttBatch.js'
import { useGanttData, isCompletedOrder } from '@/composables/gantt/useGanttData.js'
import { useGanttEditor } from '@/composables/gantt/useGanttEditor.js'
import { useGanttExport } from '@/composables/gantt/useGanttExport.js'
import { useProductionNodes } from '@/composables/gantt/useProductionNodes.js'
import { useGanttCapacity } from '@/composables/gantt/useGanttCapacity.js'


export function useGantt() {
  const canAdjustSchedules = computed(() => can('schedules:adjust'))
  const canGenerateSchedules = computed(() => can('schedules:generate'))
  const canLockSchedules = computed(() => can('schedules:lock'))
  const canUnlockSchedules = computed(() => can('schedules:unlock'))
  const canSubmitSchedules = computed(() => can('schedules:submit'))
  const canApproveSchedules = computed(() => can('schedules:approve'))
  const canRejectSchedules = computed(() => can('schedules:reject'))
  const canPublishSchedules = computed(() => can('schedules:approve'))
  const canViewNodes = computed(() => can('production_nodes:view'))
  const canManageNodes = computed(() => can('production_nodes:manage'))
  const canManageCapabilities = computed(() => can('production_nodes:capability_manage'))
  const canManageCalendars = computed(() => can('production_nodes:calendar_manage'))
  const canManageDowntime = computed(() => can('production_nodes:downtime_manage'))
  const canEdit = canAdjustSchedules
  const nodes = useProductionNodes({
    canViewNodes,
    canManageNodes,
    canManageCapabilities,
    canManageCalendars,
  })
  const data = useGanttData()
  const capacity = useGanttCapacity({
    orders: data.orders,
    riskLevel: data.riskLevel,
    productionNodes: nodes.productionNodes,
    canGenerateSchedules,
    canAdjustSchedules,
    canLockSchedules,
    canUnlockSchedules,
    canSubmitSchedules,
    canApproveSchedules,
    canRejectSchedules,
    canPublishSchedules,
    canManageDowntime,
  })

  function canAdjustOrder(order) {
    return canEdit.value && !isCompletedOrder(order)
  }

  const editor = useGanttEditor({
    dayWidth: data.dayWidth,
    ganttData: data.ganttData,
    barLeft: data.barLeft,
    canAdjustOrder,
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
    nodes.loadNodes()
    document.addEventListener('keydown', onKeyDown)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeyDown)
    editor.cleanup()
  })

  return {
    ...data,
    ...editor,
    ...nodes,
    ...capacity,
    ...batch,
    ...imageExport,
    productionNodeManager: nodes.nodeManager,
    processOptions: capacity.processOptions,
    setScheduleScope,
    isCompleted: isCompletedOrder,
    canAdjustOrder,
    canEdit,
    canAdjustSchedules,
    canGenerateSchedules,
    canLockSchedules,
    canUnlockSchedules,
    canSubmitSchedules,
    canApproveSchedules,
    canRejectSchedules,
    canPublishSchedules,
    canViewNodes,
    canManageNodes,
    canManageCapabilities,
    canManageCalendars,
    canManageDowntime,
    onKeyDown,
  }
}
