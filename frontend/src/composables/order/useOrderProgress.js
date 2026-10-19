import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useOrderProgress() {
  const progressOrder = ref(null)
  const progressLoading = ref(false)
  const progressData = ref(null)

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
    progressOrder.value = order
    progressLoading.value = true
    progressData.value = null
    try {
      progressData.value = await api.domains.orders.getWorkpieceProgress(order.id)
    } catch (error) {
      showToast(`加载进度失败: ${error.message || ''}`, 'error')
      progressOrder.value = null
    } finally {
      progressLoading.value = false
    }
  }

  return {
    progressOrder,
    progressLoading,
    progressData,
    isOrderTracking,
    progressBars,
    barPercent,
    openProgress,
  }
}
