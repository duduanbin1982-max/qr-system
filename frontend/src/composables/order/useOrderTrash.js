import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useOrderTrash({ load }) {
  const showTrash = ref(false)
  const trashOrders = ref([])
  const trashTotal = ref(0)
  const trashPage = ref(1)
  const trashPageSize = 20

  async function loadTrash() {
    try {
      const data = await api.domains.orders.trashOrders({
        page: trashPage.value,
        limit: trashPageSize,
      })
      trashOrders.value = data.orders || []
      trashTotal.value = data.total || 0
    } catch (error) {
      showToast(error.message || '加载失败', 'error')
    }
  }

  async function restoreOrder(orderId) {
    try {
      await api.domains.orders.restoreOrder(orderId)
      showToast('订单已恢复')
      await loadTrash()
      await load()
    } catch (error) {
      showToast(error.message || '恢复失败', 'error')
    }
  }

  async function permanentDelete(orderId) {
    if (!confirm('确认彻底删除该订单？所有关联数据将永久消失，不可恢复！')) return
    try {
      await api.domains.orders.purgeOrder(orderId)
      showToast('已彻底删除')
      await loadTrash()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  return {
    showTrash, trashOrders, trashTotal, trashPage, trashPageSize,
    loadTrash, restoreOrder, permanentDelete,
  }
}
