import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useOrderProgress() {
  const progressOrder = ref(null)
  const progressLoading = ref(false)
  const progressData = ref(null)
  let progressRequestToken = 0

  const isOrderTracking = computed(
    () => progressData.value?.analysis?.tracking_mode === 'order'
  )

  // Order-mode orders have no per-piece items, so the process bars must come
  // from order_processes facts instead of the workpiece-derived stats.
  const progressBars = computed(() => {
    const data = progressData.value
    if (!data) return []
    const orderStats = data.order_process_stats
    if (isOrderTracking.value && Array.isArray(orderStats) && orderStats.length) {
      return orderStats
    }
    return data.summary?.process_stats || []
  })

  function barPercent(stat) {
    const total = Number(stat?.total || 0)
    const completed = Number(stat?.completed || 0)
    if (!total || total <= 0) return 0
    return Math.min(100, Math.round((completed / total) * 100))
  }

  async function openProgress(order) {
    const requestToken = ++progressRequestToken
    progressOrder.value = order
    progressLoading.value = true
    progressData.value = null
    try {
      const data = await api.domains.orders.getWorkpieceProgress(order.id)
      if (requestToken !== progressRequestToken) return
      progressData.value = data
    } catch (error) {
      if (requestToken !== progressRequestToken) return
      showToast(`加载进度失败: ${error.message || ''}`, 'error')
      progressOrder.value = null
    } finally {
      if (requestToken === progressRequestToken) {
        progressLoading.value = false
      }
    }
  }

  function closeProgress() {
    progressRequestToken += 1
    progressOrder.value = null
    progressLoading.value = false
    progressData.value = null
  }

  return {
    progressOrder,
    progressLoading,
    progressData,
    isOrderTracking,
    progressBars,
    barPercent,
    openProgress,
    closeProgress,
  }
}
