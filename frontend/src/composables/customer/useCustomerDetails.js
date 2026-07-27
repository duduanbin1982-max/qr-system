import { ref } from 'vue'

import { api } from '@/lib/api.js'


const DETAIL_PAGE_SIZE = 10


export function useCustomerDetails(canViewOrders) {
  const detail = ref(null)
  const detailOrders = ref([])
  const showDetail = ref(false)
  const detailPage = ref(1)
  const detailTotal = ref(0)
  const detailLoading = ref(false)
  const detailError = ref('')
  let requestSequence = 0

  function resetDetailState() {
    detail.value = null
    detailOrders.value = []
    detailPage.value = 1
    detailTotal.value = 0
    detailLoading.value = false
    detailError.value = ''
  }

  async function viewDetail(customer) {
    if (!canViewOrders.value) return
    requestSequence++
    resetDetailState()
    detail.value = customer
    showDetail.value = true
    await loadDetailOrders(customer.id)
  }

  async function loadDetailOrders(customerId) {
    const requestId = ++requestSequence
    detailLoading.value = true
    detailError.value = ''
    try {
      const data = await api.domains.customers.customerOrders(customerId, {
        page: detailPage.value,
        limit: DETAIL_PAGE_SIZE,
      })
      if (!isCurrentRequest(requestId, customerId)) return
      detailOrders.value = data.orders || []
      detailTotal.value = data.total || 0
    } catch (error) {
      if (!isCurrentRequest(requestId, customerId)) return
      detailOrders.value = []
      detailTotal.value = 0
      detailError.value = error.message || '订单加载失败'
    } finally {
      if (requestId === requestSequence) detailLoading.value = false
    }
  }

  function isCurrentRequest(requestId, customerId) {
    return requestId === requestSequence
      && showDetail.value
      && detail.value?.id === customerId
  }

  function detailPrevPage() {
    if (detailLoading.value || detailPage.value <= 1) return
    detailPage.value--
    loadDetailOrders(detail.value.id)
  }

  function detailNextPage() {
    if (detailLoading.value || detailPage.value * DETAIL_PAGE_SIZE >= detailTotal.value) return
    detailPage.value++
    loadDetailOrders(detail.value.id)
  }

  function closeDetail() {
    requestSequence++
    showDetail.value = false
    resetDetailState()
  }

  return {
    showDetail,
    detail,
    detailOrders,
    detailLoading,
    detailError,
    detailPage,
    detailTotal,
    detailPageSize: DETAIL_PAGE_SIZE,
    viewDetail,
    loadDetailOrders,
    detailPrevPage,
    detailNextPage,
    closeDetail,
  }
}
