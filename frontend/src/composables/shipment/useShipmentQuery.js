import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useShipmentQuery() {
  const shipments = ref([])
  const loading = ref(true)
  const total = ref(0)
  const page = ref(1)
  const limit = ref(20)
  const filterStatus = ref('')
  const searchKeyword = ref('')
  const pendingCount = ref(0)
  const completedCount = ref(0)
  const receivableTotal = ref(0)
  const paidTotal = ref(0)
  const unpaidTotal = ref(0)

  async function load() {
    loading.value = true
    try {
      const params = { page: page.value, limit: limit.value }
      if (filterStatus.value) params.status = filterStatus.value
      if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
      const data = await api.domains.shipments.listShipments(params)
      shipments.value = data.shipments || []
      total.value = data.total || 0
      pendingCount.value = data.pending_count ?? 0
      completedCount.value = data.completed_count ?? 0
      receivableTotal.value = Number(data.receivable_total || 0)
      paidTotal.value = Number(data.paid_total || 0)
      unpaidTotal.value = Number(data.unpaid_total || 0)
    } catch (error) {
      showToast(error.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  function prevPage() {
    if (page.value <= 1) return
    page.value--
    return load()
  }

  function nextPage() {
    if (page.value * limit.value >= total.value) return
    page.value++
    return load()
  }

  function exportExcel() {
    const query = new URLSearchParams({
      keyword: searchKeyword.value,
      status: filterStatus.value,
    })
    window.open(`/api/shipments/export?${query.toString()}`, '_blank')
  }

  return {
    shipments,
    loading,
    total,
    page,
    limit,
    filterStatus,
    searchKeyword,
    pendingCount,
    completedCount,
    receivableTotal,
    paidTotal,
    unpaidTotal,
    load,
    prevPage,
    nextPage,
    exportExcel,
  }
}
