import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useGanttBatch({
  canEdit,
  canAdjustOrder,
  filteredOrders,
  isCompleted,
  reload,
}) {
  const selectedOrderIds = ref([])
  const batchDays = ref(1)
  const allSelected = ref(false)

  function editableIds() {
    return filteredOrders.value.filter(order => !isCompleted(order)).map(order => order.id)
  }

  function toggleAll() {
    if (!canEdit.value) return
    allSelected.value = !allSelected.value
    selectedOrderIds.value = allSelected.value ? editableIds() : []
  }

  function toggleOrder(order) {
    if (!canAdjustOrder(order)) return
    const id = typeof order === 'object' ? order.id : order
    const index = selectedOrderIds.value.indexOf(id)
    if (index >= 0) selectedOrderIds.value.splice(index, 1)
    else selectedOrderIds.value.push(id)
    const ids = filteredOrders.value.filter(canAdjustOrder).map(item => item.id)
    allSelected.value = ids.length > 0 && ids.every(item => selectedOrderIds.value.includes(item))
  }

  function selectedEditableIds() {
    const allowed = new Set(editableIds())
    return selectedOrderIds.value.filter(id => allowed.has(id))
  }

  async function batchShift(direction) {
    const orderIds = selectedEditableIds()
    if (!orderIds.length) {
      showToast('请先选择未完成订单', 'warning')
      return
    }
    const days = batchDays.value * (direction === 'right' ? 1 : -1)
    await shift(orderIds, days, '批量偏移失败')
    allSelected.value = false
  }

  async function shiftDays(direction, big) {
    const orderIds = selectedEditableIds()
    if (!orderIds.length) return
    const days = (big ? 7 : 1) * direction
    await shift(orderIds, days, '批量调整失败')
  }

  async function shift(orderIds, days, errorMessage) {
    try {
      const result = await api.domains.production.batchShiftSchedule({
        order_ids: orderIds,
        days,
      })
      showToast(result.message || `已偏移 ${result.count || 0} 个订单`)
      selectedOrderIds.value = []
      await reload()
    } catch (error) {
      showToast(error.message || errorMessage, 'error')
    }
  }

  function resetSelection() {
    selectedOrderIds.value = []
    allSelected.value = false
  }

  return {
    selectedOrderIds,
    batchDays,
    allSelected,
    toggleAll,
    toggleOrder,
    batchShift,
    shiftDays,
    resetSelection,
  }
}
