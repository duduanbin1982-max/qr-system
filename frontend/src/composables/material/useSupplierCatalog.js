import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useSupplierCatalog() {
  const suppliers = ref([])
  const supplierOptions = ref([])
  const supplierLoading = ref(false)
  const supplierError = ref('')
  const supplierSearchText = ref('')
  const supplierPage = ref(1)
  const supplierPageSize = 20
  const supplierTotal = ref(0)
  let listRequestSequence = 0
  let optionsRequestSequence = 0

  async function loadSuppliers() {
    const requestId = ++listRequestSequence
    supplierLoading.value = true
    supplierError.value = ''
    const params = { page: supplierPage.value, limit: supplierPageSize }
    const keyword = supplierSearchText.value.trim()
    if (keyword) params.keyword = keyword
    try {
      const data = await api.domains.materials.listSuppliers(params)
      if (requestId !== listRequestSequence) return
      suppliers.value = data.suppliers || []
      supplierTotal.value = Number(data.total || 0)
    } catch (error) {
      if (requestId !== listRequestSequence) return
      suppliers.value = []
      supplierTotal.value = 0
      supplierError.value = error.message || '供应商加载失败'
      showToast(supplierError.value, 'error')
    } finally {
      if (requestId === listRequestSequence) supplierLoading.value = false
    }
  }

  async function loadSupplierOptions() {
    const requestId = ++optionsRequestSequence
    const allSuppliers = []
    let currentPage = 1
    let expectedTotal = 0
    try {
      do {
        const data = await api.domains.materials.listSuppliers({ page: currentPage, limit: 500 })
        if (requestId !== optionsRequestSequence) return
        const pageSuppliers = data.suppliers || []
        allSuppliers.push(...pageSuppliers)
        expectedTotal = Number(data.total || 0)
        currentPage += 1
        if (!pageSuppliers.length) break
      } while (allSuppliers.length < expectedTotal)
      supplierOptions.value = allSuppliers
    } catch (error) {
      if (requestId !== optionsRequestSequence) return
      supplierOptions.value = []
      showToast(error.message || '供应商选项加载失败', 'error')
    }
  }

  function searchSuppliers() {
    supplierPage.value = 1
    return loadSuppliers()
  }

  function previousSupplierPage() {
    if (supplierPage.value <= 1 || supplierLoading.value) return
    supplierPage.value -= 1
    return loadSuppliers()
  }

  function nextSupplierPage() {
    if (supplierPage.value * supplierPageSize >= supplierTotal.value || supplierLoading.value) return
    supplierPage.value += 1
    return loadSuppliers()
  }

  async function refreshSuppliersAfterMutation() {
    if (suppliers.value.length <= 1 && supplierPage.value > 1) supplierPage.value -= 1
    await Promise.all([loadSuppliers(), loadSupplierOptions()])
  }

  return {
    suppliers,
    supplierOptions,
    supplierLoading,
    supplierError,
    supplierSearchText,
    supplierPage,
    supplierPageSize,
    supplierTotal,
    loadSuppliers,
    loadSupplierOptions,
    searchSuppliers,
    previousSupplierPage,
    nextSupplierPage,
    refreshSuppliersAfterMutation,
  }
}
