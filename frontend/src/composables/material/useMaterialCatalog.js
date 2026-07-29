import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


const EMPTY_SUMMARY = { total: 0, low_stock: 0, inventory_value: 0 }

export function useMaterialCatalog() {
  const materials = ref([])
  const loading = ref(false)
  const loadError = ref('')
  const searchText = ref('')
  const materialTypeFilter = ref('')
  const materialTypeOptions = ref([])
  const page = ref(1)
  const pageSize = 20
  const total = ref(0)
  const summary = ref({ ...EMPTY_SUMMARY })
  let requestSequence = 0

  const totalCount = computed(() => Number(summary.value.total || 0))
  const lowStockCount = computed(() => Number(summary.value.low_stock || 0))
  const totalInventoryValue = computed(() => Number(summary.value.inventory_value || 0).toFixed(2))

  async function load() {
    const requestId = ++requestSequence
    loading.value = true
    loadError.value = ''
    const params = { page: page.value, limit: pageSize }
    const keyword = searchText.value.trim()
    if (keyword) params.keyword = keyword
    if (materialTypeFilter.value) params.material_type = materialTypeFilter.value

    try {
      const data = await api.domains.materials.listMaterials(params)
      if (requestId !== requestSequence) return
      materials.value = data.materials || []
      total.value = Number(data.total || 0)
      summary.value = data.summary || { ...EMPTY_SUMMARY, total: total.value }
      materialTypeOptions.value = data.material_types || []
    } catch (error) {
      if (requestId !== requestSequence) return
      materials.value = []
      total.value = 0
      summary.value = { ...EMPTY_SUMMARY }
      materialTypeOptions.value = []
      loadError.value = error.message || '物料数据加载失败'
      showToast(loadError.value, 'error')
    } finally {
      if (requestId === requestSequence) loading.value = false
    }
  }

  function searchAndLoad() {
    page.value = 1
    return load()
  }

  function filterAndLoad() {
    page.value = 1
    return load()
  }

  function previousPage() {
    if (page.value <= 1 || loading.value) return
    page.value -= 1
    return load()
  }

  function nextPage() {
    if (page.value * pageSize >= total.value || loading.value) return
    page.value += 1
    return load()
  }

  async function refreshAfterDelete() {
    if (materials.value.length <= 1 && page.value > 1) page.value -= 1
    await load()
  }

  function getAbcClass(material) {
    return material.abc_class || 'C'
  }

  return {
    materials,
    loading,
    loadError,
    searchText,
    materialTypeFilter,
    materialTypeOptions,
    page,
    pageSize,
    total,
    summary,
    totalCount,
    lowStockCount,
    totalInventoryValue,
    load,
    searchAndLoad,
    filterAndLoad,
    previousPage,
    nextPage,
    refreshAfterDelete,
    getAbcClass,
  }
}
