import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'

const VIEW_KEY = 'inventory-workbench:v1:view'
const FILTER_KEY = 'inventory-workbench:v1:filters'

function readJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null')
    return value == null ? fallback : value
  } catch (_) {
    return fallback
  }
}

export function useInventoryProductGroups() {
  const capabilities = ref({ product_query_enabled: false })
  const viewMode = ref(localStorage.getItem(VIEW_KEY) || 'order')
  const groups = ref([])
  const total = ref(0)
  const page = ref(1)
  // The production catalogue currently exceeds 50 product groups. Prefer the
  // API maximum so the normal view shows the complete catalogue, while the
  // pager still supports future catalogues larger than 200 groups.
  const limit = ref(200)
  const filters = ref(readJson(FILTER_KEY, { keyword: '', low_stock: false, location: '', quality_status: '', identity_status: '' }))
  const loading = ref(false)
  const error = ref('')
  const selectedProduct = ref(null)
  const selectedDetails = ref(null)
  const drawerOpen = ref(false)
  let detailRequest = 0

  const enabled = computed(() => Boolean(capabilities.value.product_query_enabled))

  async function loadCapabilities() {
    capabilities.value = await api.domains.inventory.inventoryCapabilities()
    if (viewMode.value === 'product' && enabled.value && !groups.value.length) {
      await loadGroups()
    }
    return capabilities.value
  }

  function setViewMode(mode) {
    viewMode.value = mode === 'product' ? 'product' : 'order'
    localStorage.setItem(VIEW_KEY, viewMode.value)
    if (viewMode.value === 'product' && enabled.value && !groups.value.length) loadGroups()
  }

  async function loadGroups() {
    if (!enabled.value) return
    loading.value = true
    error.value = ''
    localStorage.setItem(FILTER_KEY, JSON.stringify(filters.value))
    try {
      const data = await api.domains.inventory.listProductGroups({ ...filters.value, low_stock: filters.value.low_stock ? '1' : '', page: page.value, limit: limit.value })
      groups.value = data.items || []
      total.value = Number(data.total || 0)
    } catch (err) {
      error.value = err.message || '产品库存加载失败'
    } finally {
      loading.value = false
    }
  }

  function searchGroups() {
    page.value = 1
    return loadGroups()
  }

  function changePage(nextPage) {
    const lastPage = Math.max(1, Math.ceil(total.value / limit.value))
    page.value = Math.min(Math.max(Number(nextPage) || 1, 1), lastPage)
    return loadGroups()
  }

  function changeLimit(nextLimit) {
    const allowed = [50, 100, 200]
    const parsed = Number(nextLimit)
    limit.value = allowed.includes(parsed) ? parsed : 200
    page.value = 1
    return loadGroups()
  }

  function resetFilters() {
    filters.value = { keyword: '', low_stock: false, location: '', quality_status: '', identity_status: '' }
    page.value = 1
    return loadGroups()
  }

  async function openProduct(product) {
    const requestId = ++detailRequest
    selectedProduct.value = product
    selectedDetails.value = null
    drawerOpen.value = true
    try {
      const details = await api.domains.inventory.productGroupDetails(product.product_id)
      if (requestId === detailRequest) selectedDetails.value = details
    } catch (err) {
      if (requestId === detailRequest) error.value = err.message || '产品详情加载失败'
    }
  }

  function closeDrawer() {
    drawerOpen.value = false
    selectedProduct.value = null
    selectedDetails.value = null
  }

  onMounted(() => { loadCapabilities() })

  return {
    state: { capabilities, enabled, viewMode, groups, total, page, limit, filters, loading, error, selectedProduct, selectedDetails, drawerOpen },
    actions: { loadCapabilities, setViewMode, loadGroups, searchGroups, changePage, changeLimit, resetFilters, openProduct, closeDrawer },
  }
}
