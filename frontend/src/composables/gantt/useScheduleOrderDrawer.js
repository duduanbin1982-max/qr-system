import { ref } from 'vue'

import { api } from '@/lib/api.js'

export function useScheduleOrderDrawer() {
  const orderDrawerOpen = ref(false)
  const selectedScheduleOrder = ref(null)
  const selectedOrderOperations = ref([])
  const selectedOrderRevisions = ref([])
  const orderDrawerLoading = ref(false)
  const orderDrawerError = ref('')

  async function openOrderDrawer(order) {
    if (!order?.id) return
    selectedScheduleOrder.value = order
    selectedOrderOperations.value = []
    selectedOrderRevisions.value = []
    orderDrawerError.value = ''
    orderDrawerOpen.value = true
    orderDrawerLoading.value = true
    try {
      const [operations, revisions] = await Promise.all([
        api.domains.production.getOrderOperationSchedule(order.id),
        api.domains.production.listOrderScheduleRevisions(order.id, { limit: 100 }),
      ])
      selectedOrderOperations.value = operations.operations || []
      selectedOrderRevisions.value = revisions.revisions || []
    } catch (error) {
      orderDrawerError.value = error?.message || '加载订单排程详情失败'
    } finally {
      orderDrawerLoading.value = false
    }
  }

  function closeOrderDrawer() {
    orderDrawerOpen.value = false
  }

  return {
    orderDrawerOpen,
    selectedScheduleOrder,
    selectedOrderOperations,
    selectedOrderRevisions,
    orderDrawerLoading,
    orderDrawerError,
    openOrderDrawer,
    closeOrderDrawer,
  }
}
