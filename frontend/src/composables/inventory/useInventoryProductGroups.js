import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { createInventoryQueryCoordinator } from './inventoryQueryCoordinator.js'

const VIEW_KEY = 'inventory-workbench:v1:view'
const FILTER_KEY = 'inventory-workbench:v1:filters'
const PRESET_KEY = 'inventory-workbench:v1:product-presets'
const COLUMN_KEY = 'inventory-workbench:v1:product-columns'
const DEFAULT_FILTERS = { keyword: '', low_stock: false, location: '', quality_status: '', identity_status: '', specifications: [] }
const EMPTY_SUMMARY = { total_items: 0, total_quantity: 0, total_value: 0, low_stock: 0, today_in: 0, today_out: 0 }
const PRODUCT_COLUMNS = [
  { key: 'product_code', label: '产品编码', required: true },
  { key: 'product_name', label: '产品名称', required: true },
  { key: 'specification', label: '规格', required: true },
  { key: 'quantity', label: '总库存' },
  { key: 'reserved_quantity', label: '预留' },
  { key: 'frozen_quantity', label: '冻结' },
  { key: 'available_quantity', label: '可用' },
  { key: 'order_count', label: '订单数' },
  { key: 'lot_count', label: '批次数' },
  { key: 'location_count', label: '库位数' },
  { key: 'alert', label: '预警' },
  { key: 'actions', label: '操作', required: true },
]

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
  const summary = ref({ ...EMPTY_SUMMARY })
  const loading = ref(false)
  const summaryLoading = ref(false)
  const error = ref('')
  const sortBy = ref('alert')
  const sortDir = ref('desc')
  const visibleColumns = ref(readColumns(COLUMN_KEY, PRODUCT_COLUMNS))
  const selectedIds = ref([])
  const selectedProduct = ref(null)
  const selectedDetails = ref(null)
  const drawerOpen = ref(false)
  const queryCoordinator = createInventoryQueryCoordinator()
  let detailRequest = 0

  const enabled = computed(() => Boolean(capabilities.value.product_query_enabled))
  const canExport = computed(() => can('inventory:export'))
  const selectedCount = computed(() => selectedIds.value.length)

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
    if (viewMode.value === 'product' && enabled.value) return loadGroups()
  }

  watch(viewMode, (mode) => {
    localStorage.setItem(VIEW_KEY, mode)
  })

  function querySnapshot() {
    const listParams = {
      ...filters.value,
      specifications: [...filters.value.specifications],
      low_stock: filters.value.low_stock ? '1' : '',
      page: page.value,
      limit: limit.value,
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    }
    const summaryParams = {
      ...filters.value,
      specifications: [...filters.value.specifications],
      low_stock: filters.value.low_stock ? '1' : '',
      view: 'product',
    }
    return { listParams, summaryParams }
  }

  async function loadGroups() {
    if (!enabled.value) return
    const snapshot = querySnapshot()
    const request = queryCoordinator.begin(snapshot)
    loading.value = true
    summaryLoading.value = true
    error.value = ''
    localStorage.setItem(FILTER_KEY, JSON.stringify(filters.value))
    try {
      const [data, summaryData] = await Promise.all([
        api.domains.inventory.listProductGroups(snapshot.listParams),
        api.domains.inventory.inventoryStats(snapshot.summaryParams),
      ])
      if (!queryCoordinator.isCurrent(request)) return
      groups.value = data.items || []
      total.value = Number(data.total || 0)
      summary.value = { ...EMPTY_SUMMARY, ...summaryData }
      selectedIds.value = selectedIds.value.filter(id => groups.value.some(item => item.product_id === id))
    } catch (err) {
      if (!queryCoordinator.isCurrent(request)) return
      error.value = err.message || '产品库存加载失败'
    } finally {
      if (queryCoordinator.isCurrent(request)) {
        loading.value = false
        summaryLoading.value = false
      }
    }
  }

  function loadSummary() {
    return loadGroups()
  }

  function cancelPendingLoad() {
    queryCoordinator.invalidate()
    loading.value = false
    summaryLoading.value = false
  }

  function readColumns(key, columns) {
    const defaults = columns.map(column => column.key)
    try {
      const stored = JSON.parse(localStorage.getItem(key) || 'null')
      if (!Array.isArray(stored)) return defaults
      const allowed = new Set(defaults)
      const required = columns.filter(column => column.required).map(column => column.key)
      return [...required, ...new Set(stored.filter(keyName => allowed.has(keyName) && !required.includes(keyName)))]
    } catch (_) {
      return defaults
    }
  }

  function persistColumns() { localStorage.setItem(COLUMN_KEY, JSON.stringify(visibleColumns.value)) }

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

  function setSort(key) {
    if (!PRODUCT_COLUMNS.some(column => column.key === key) || key === 'actions') return
    if (sortBy.value === key) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
    else { sortBy.value = key; sortDir.value = 'asc' }
    page.value = 1
    return loadGroups()
  }

  function setVisibleColumns(keys) {
    const allowed = new Set(PRODUCT_COLUMNS.map(column => column.key))
    const required = PRODUCT_COLUMNS.filter(column => column.required).map(column => column.key)
    visibleColumns.value = [...required, ...new Set(keys.filter(key => allowed.has(key) && !required.includes(key)))]
    persistColumns()
  }

  function resetVisibleColumns() { setVisibleColumns(PRODUCT_COLUMNS.map(column => column.key)) }

  function toggleSelect(id) {
    selectedIds.value = selectedIds.value.includes(id)
      ? selectedIds.value.filter(item => item !== id)
      : [...selectedIds.value, id]
  }

  function toggleSelectAll() {
    const pageIds = groups.value.map(item => item.product_id)
    const allSelected = pageIds.length > 0 && pageIds.every(id => selectedIds.value.includes(id))
    selectedIds.value = allSelected
      ? selectedIds.value.filter(id => !pageIds.includes(id))
      : [...new Set([...selectedIds.value, ...pageIds])]
  }

  function clearSelection() { selectedIds.value = [] }

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
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    }
    delete params.specifications
    if (selectedIds.value.length) params.product_id = selectedIds.value.join(',')
    window.open(api.domains.inventory.productGroupExportUrl(params), '_blank')
  }

  function exportGroupsCsv() {
    const params = {
      ...filters.value,
      low_stock: filters.value.low_stock ? '1' : '',
      specification: (filters.value.specifications || []).join(','),
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    }
    delete params.specifications
    if (selectedIds.value.length) params.product_id = selectedIds.value.join(',')
    window.open(api.domains.inventory.productGroupExportCsvUrl(params), '_blank')
  }

  function exportSelected() {
    if (!selectedIds.value.length) return
    if (!window.confirm(`确认导出已选 ${selectedIds.value.length} 个产品吗？`)) return
    exportGroups()
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
  onUnmounted(cancelPendingLoad)

  return {
    state: { capabilities, enabled, canExport, viewMode, groups, total, page, limit, filters, filterOptions, summary, summaryLoading, loading, error, selectedProduct, selectedDetails, drawerOpen, savedFilters, sortBy, sortDir, visibleColumns, productColumns: PRODUCT_COLUMNS, selectedIds, selectedCount },
    actions: { loadCapabilities, loadFilterOptions, loadGroups, loadSummary, cancelPendingLoad, searchGroups, changePage, changeLimit, setViewMode, setSort, setVisibleColumns, resetVisibleColumns, toggleSelect, toggleSelectAll, clearSelection, resetFilters, setFilter, clearFilter, saveFilter, applyFilter, removeFilterPreset, exportGroups, exportGroupsCsv, exportSelected, openProduct, closeDrawer },
  }
}
