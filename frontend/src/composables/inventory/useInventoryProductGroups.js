import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'

const VIEW_KEY = 'inventory-workbench:v1:view'
const FILTER_KEY = 'inventory-workbench:v1:filters'
const PRESET_KEY = 'inventory-workbench:v1:product-presets'
const DEFAULT_FILTERS = { keyword: '', low_stock: false, location: '', quality_status: '', identity_status: '', specifications: [] }

function readJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null')
    return value == null ? fallback : value
  } catch (_) {
    return fallback
  }
}

export function useInventoryProductGroups() {
  const storedFilters = readJson(FILTER_KEY, {})
  const capabilities = ref({ product_query_enabled: false })
  const viewMode = ref(localStorage.getItem(VIEW_KEY) || 'order')
  const groups = ref([])
  const total = ref(0)
  const page = ref(1)
  // The production catalogue currently exceeds 50 product groups. Prefer the
  // API maximum so the normal view shows the complete catalogue, while the
  // pager still supports future catalogues larger than 200 groups.
  const limit = ref(200)
  const filters = ref({
    ...DEFAULT_FILTERS,
    ...storedFilters,
    specifications: Array.isArray(storedFilters.specifications) ? storedFilters.specifications : [],
  })
  const storedPresets = readJson(PRESET_KEY, [])
  const savedFilters = ref(Array.isArray(storedPresets) ? storedPresets : [])
  const filterOptions = ref({ specifications: [], quality_statuses: [], locations: [] })
  const summary = ref({ total_items: 0, total_quantity: 0, total_value: 0, low_stock: 0, today_in: 0, today_out: 0 })
  const loading = ref(false)
  const error = ref('')
  const selectedProduct = ref(null)
  const selectedDetails = ref(null)
  const drawerOpen = ref(false)
  let detailRequest = 0

  const enabled = computed(() => Boolean(capabilities.value.product_query_enabled))
  const canExport = computed(() => can('inventory:export'))

  async function loadCapabilities() {
    capabilities.value = await api.domains.inventory.inventoryCapabilities()
    if (enabled.value) await loadFilterOptions()
    if (viewMode.value === 'product' && enabled.value && !groups.value.length) {
      await loadGroups()
    }
    return capabilities.value
  }

  async function loadFilterOptions() {
    try {
      filterOptions.value = await api.domains.inventory.inventoryFilterOptions({ view: 'product' })
    } catch (_) {
      // Keep the table usable when an older server does not expose options yet.
    }
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
      await loadSummary()
    } catch (err) {
      error.value = err.message || '产品库存加载失败'
    } finally {
      loading.value = false
    }
  }

  async function loadSummary() {
    try {
      summary.value = await api.domains.inventory.inventoryStats({
        ...filters.value,
        low_stock: filters.value.low_stock ? '1' : '',
        view: 'product',
      })
    } catch (_) {
      // Summary is supplemental; leave the previous values visible.
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
    filters.value = { ...DEFAULT_FILTERS, specifications: [] }
    page.value = 1
    return loadGroups()
  }

  function setFilter({ key, value }) {
    if (!(key in filters.value)) return
    filters.value = {
      ...filters.value,
      [key]: key === 'specifications' ? (Array.isArray(value) ? [...value] : []) : value,
    }
  }

  function clearFilter(input) {
    const key = input?.key || input
    const value = input?.value
    const nextSpecifications = key === 'specifications' && value
      ? filters.value.specifications.filter(item => item !== value)
      : []
    setFilter({ key, value: key === 'low_stock' ? false : key === 'specifications' ? nextSpecifications : '' })
    return searchGroups()
  }

  function persistPresets() {
    localStorage.setItem(PRESET_KEY, JSON.stringify(savedFilters.value))
  }

  function saveFilter(name) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    savedFilters.value = [
      ...savedFilters.value.filter(item => item.name !== name),
      { id, name, filters: JSON.parse(JSON.stringify(filters.value)), created_at: new Date().toISOString() },
    ].slice(-12)
    persistPresets()
  }

  function applyFilter(preset) {
    if (!preset?.filters) return
    Object.entries(preset.filters).forEach(([key, value]) => setFilter({ key, value }))
    return searchGroups()
  }

  function removeFilterPreset(id) {
    savedFilters.value = savedFilters.value.filter(item => item.id !== id)
    persistPresets()
  }

  function exportGroups() {
    const params = {
      ...filters.value,
      low_stock: filters.value.low_stock ? '1' : '',
      specification: (filters.value.specifications || []).join(','),
    }
    delete params.specifications
    window.open(api.domains.inventory.productGroupExportUrl(params), '_blank')
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
    state: { capabilities, enabled, canExport, viewMode, groups, total, page, limit, filters, filterOptions, summary, loading, error, selectedProduct, selectedDetails, drawerOpen, savedFilters },
    actions: { loadCapabilities, loadFilterOptions, loadGroups, loadSummary, searchGroups, changePage, changeLimit, resetFilters, setFilter, clearFilter, saveFilter, applyFilter, removeFilterPreset, exportGroups, openProduct, closeDrawer },
  }
}
