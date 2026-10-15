import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useSchedulePriority({ closeOrderDrawer, load, loadCapacity }) {
  const priorityDrawerOpen = ref(false)
  const priorityOrder = ref(null)
  const prioritySaving = ref(false)

  function openPriorityDrawer(order) {
    priorityOrder.value = order
    closeOrderDrawer?.()
    priorityDrawerOpen.value = true
  }

  async function savePriorityChange(payload) {
    if (!priorityOrder.value?.id || prioritySaving.value) return
    prioritySaving.value = true
    try {
      await api.domains.production.updateScheduleOrderPriority(priorityOrder.value.id, {
        ...payload,
        expected_priority_version: Number(priorityOrder.value.priority_version || 1),
      })
      priorityDrawerOpen.value = false
      showToast('订单优先级已更新，已标记为待重新排程')
      await Promise.all([load(), loadCapacity?.()])
    } catch (error) {
      showToast(error.message || '调整优先级失败', 'error')
    } finally {
      prioritySaving.value = false
    }
  }

  return { priorityDrawerOpen, priorityOrder, prioritySaving, openPriorityDrawer, savePriorityChange }
}
