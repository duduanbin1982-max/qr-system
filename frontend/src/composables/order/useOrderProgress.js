import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useOrderProgress() {
  const progressOrder = ref(null)
  const progressLoading = ref(false)
  const progressData = ref(null)

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

  return { progressOrder, progressLoading, progressData, openProgress }
}
