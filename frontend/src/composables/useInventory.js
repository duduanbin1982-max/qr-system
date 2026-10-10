import { ref, onMounted, onUnmounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
import { createInventoryQueryCoordinator } from '@/composables/inventory/inventoryQueryCoordinator.js'

const EMPTY_SUMMARY = { total_items: 0, total_quantity: 0, total_value: 0, low_stock: 0, today_in: 0, today_out: 0 }

export function useInventory() {
  const FILTER_PRESETS_KEY = 'inventory-workbench:v1:order-presets'
  const COLUMN_KEY = 'inventory-workbench:v1:order-columns'
  const ORDER_COLUMNS = [
    { key: 'product_name', label: '产品名称' },
    { key: 'order_no', label: '订单号' },
    { key: 'customer', label: '客户' },
    { key: 'product_model', label: '产品型号', required: true },
    { key: 'specification', label: '规格' },
    { key: 'category', label: 'ABC' },
    { key: 'quantity', label: '数量' },
    { key: 'safe_stock', label: '安全库存' },
    { key: 'location', label: '存放位置' },
    { key: 'unit', label: '单位' },
    { key: 'actions', label: '操作', required: true },
  ]
  const items = ref([])
  const orderOptions = ref([])
  const loading = ref(true)
  const total = ref(0)
  const page = ref(1)
  const limit = ref(100)
  const searchKeyword = ref('')
  const lowStockOnly = ref(false)
  const locationFilter = ref('')
  const locations = ref([])
  const specificationFilter = ref([])
  const qualityStatusFilter = ref('')
  const sortBy = ref('updated_at')
  const sortDir = ref('desc')
  const summaryLoading = ref(false)
  const visibleColumns = ref(readColumns(COLUMN_KEY, ORDER_COLUMNS))
  const selectedIds = ref([])
  const filterOptions = ref({ specifications: [], quality_statuses: [], locations: [] })
  const savedFilters = ref(readSavedFilters(FILTER_PRESETS_KEY))
  const queryCoordinator = createInventoryQueryCoordinator()
  const filters = computed(() => ({
    keyword: searchKeyword.value,
    low_stock: lowStockOnly.value,
    location: locationFilter.value,
    quality_status: qualityStatusFilter.value,
    specifications: [...specificationFilter.value],
  }))

  const showLogs = ref(false)
  const logs = ref([])
  const logsLoading = ref(false)

  const showTurnover = ref(false)
  const turnoverData = ref([])
  const turnoverLoading = ref(false)

  const showCount = ref(false)
  const countLoading = ref(false)
  const countTask = ref(null)
  const countItems = ref([])

  const showModal = ref(false)
  const modalEdit = ref(false)
  const modalId = ref(null)
  const form = ref({
    product_model: '',
    product_name: '',
    specification: '',
    quantity: 0,
    safe_stock: 0,
    location: '',
    unit: '件',
    remark: '',
  })

  const showMoveModal = ref(false)
  const moveType = ref('in')
  const moveTarget = ref(null)
  const moveQty = ref(1)
  const moveOrderId = ref('')
  const moveLotNo = ref('')
  const moveSerialNo = ref('')

  const stats = ref({ ...EMPTY_SUMMARY })
  const lowCount = computed(() => stats.value.low_stock || items.value.filter((item) => item.is_low).length)
  const totalQty = computed(() => stats.value.total_quantity || items.value.reduce((sum, item) => sum + (item.quantity || 0), 0))
  const inventoryValue = computed(() => items.value.reduce((sum, item) => sum + (item.price || 0) * (item.quantity || 0), 0))
  const selectedCount = computed(() => selectedIds.value.length)

  function readSavedFilters(key) {
    try {
      const stored = JSON.parse(localStorage.getItem(key) || '[]')
      return Array.isArray(stored) ? stored : []
    } catch (_) {
      return []
    }
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

  function persistSavedFilters() {
    localStorage.setItem(FILTER_PRESETS_KEY, JSON.stringify(savedFilters.value))
  }

  function setFilter({ key, value }) {
    if (key === 'keyword') searchKeyword.value = value
    else if (key === 'low_stock') lowStockOnly.value = Boolean(value)
    else if (key === 'location') locationFilter.value = value || ''
    else if (key === 'quality_status') qualityStatusFilter.value = value || ''
    else if (key === 'specifications') specificationFilter.value = Array.isArray(value) ? [...value] : []
  }

  function clearFilter(input) {
    const key = input?.key || input
    const value = input?.value
    const nextSpecifications = key === 'specifications' && value
      ? specificationFilter.value.filter(item => item !== value)
      : []
    setFilter({
      key,
      value: key === 'low_stock' ? false : key === 'specifications' ? nextSpecifications : '',
    })
    return search()
  }

  function saveFilter(name) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    savedFilters.value = [
      ...savedFilters.value.filter(item => item.name !== name),
      { id, name, filters: JSON.parse(JSON.stringify(filters.value)), created_at: new Date().toISOString() },
    ].slice(-12)
    persistSavedFilters()
    showToast(`已保存筛选“${name}”`)
  }

  function applyFilter(preset) {
    if (!preset?.filters) return
    Object.entries(preset.filters).forEach(([key, value]) => setFilter({ key, value }))
    return search()
  }

  function removeFilterPreset(id) {
    savedFilters.value = savedFilters.value.filter(item => item.id !== id)
    persistSavedFilters()
  }

  const canEdit = computed(() => can('inventory:edit'))
  const canDelete = computed(() => can('inventory:delete'))
  const canCreate = computed(() => can('inventory:create'))
  const canExport = computed(() => can('inventory:export'))

  function querySnapshot() {
    const listParams = {}
    if (searchKeyword.value.trim()) listParams.keyword = searchKeyword.value.trim()
    if (lowStockOnly.value) listParams.low_stock = '1'
    if (locationFilter.value) listParams.location = locationFilter.value
    if (specificationFilter.value.length) listParams.specification = specificationFilter.value.join(',')
    if (qualityStatusFilter.value) listParams.quality_status = qualityStatusFilter.value
    listParams.page = page.value
    listParams.limit = limit.value
    listParams.sort_by = sortBy.value
    listParams.sort_dir = sortDir.value
    const summaryParams = { ...listParams }
    delete summaryParams.page
    delete summaryParams.limit
    delete summaryParams.sort_by
    delete summaryParams.sort_dir
    return { listParams, summaryParams }
  }

  async function load() {
    const snapshot = querySnapshot()
    const request = queryCoordinator.begin(snapshot)
    loading.value = true
    summaryLoading.value = true
    try {
      const [data, summaryData] = await Promise.all([
        api.domains.inventory.listInventory(snapshot.listParams),
        api.domains.inventory.inventoryStats(snapshot.summaryParams),
      ])
      if (!queryCoordinator.isCurrent(request)) return
      items.value = data.items || []
      total.value = Number(data.total || 0)
      stats.value = { ...EMPTY_SUMMARY, ...summaryData }
      selectedIds.value = selectedIds.value.filter(id => items.value.some(item => item.id === id))
    } catch (error) {
      if (!queryCoordinator.isCurrent(request)) return
      showToast(error.message || '加载失败', 'error')
    } finally {
      if (queryCoordinator.isCurrent(request)) {
        loading.value = false
        summaryLoading.value = false
      }
    }
  }

  function loadStats() {
    return load()
  }

  function cancelPendingLoad() {
    queryCoordinator.invalidate()
    loading.value = false
    summaryLoading.value = false
  }

  function search() {
    page.value = 1
    return load()
  }

  function resetFilters() {
    searchKeyword.value = ''
    lowStockOnly.value = false
    locationFilter.value = ''
    specificationFilter.value = []
    qualityStatusFilter.value = ''
    page.value = 1
    return load()
  }

  function changePage(nextPage) {
    const lastPage = Math.max(1, Math.ceil(total.value / limit.value))
    page.value = Math.min(Math.max(Number(nextPage) || 1, 1), lastPage)
    return load()
  }

  function changeLimit(nextLimit) {
    const allowed = [50, 100, 200, 500]
    const parsed = Number(nextLimit)
    limit.value = allowed.includes(parsed) ? parsed : 100
    page.value = 1
    return load()
  }

  function setSort(key) {
    if (!ORDER_COLUMNS.some(column => column.key === key) || key === 'actions') return
    if (sortBy.value === key) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
    else { sortBy.value = key; sortDir.value = 'asc' }
    page.value = 1
    return load()
  }

  function setVisibleColumns(keys) {
    const allowed = new Set(ORDER_COLUMNS.map(column => column.key))
    const required = ORDER_COLUMNS.filter(column => column.required).map(column => column.key)
    visibleColumns.value = [...required, ...new Set(keys.filter(key => allowed.has(key) && !required.includes(key)))]
    persistColumns()
  }

  function resetVisibleColumns() { setVisibleColumns(ORDER_COLUMNS.map(column => column.key)) }

  function toggleSelect(id) {
    selectedIds.value = selectedIds.value.includes(id)
      ? selectedIds.value.filter(item => item !== id)
      : [...selectedIds.value, id]
  }

  function toggleSelectAll() {
    const pageIds = items.value.map(item => item.id)
    const allSelected = pageIds.length > 0 && pageIds.every(id => selectedIds.value.includes(id))
    selectedIds.value = allSelected
      ? selectedIds.value.filter(id => !pageIds.includes(id))
      : [...new Set([...selectedIds.value, ...pageIds])]
  }

  function clearSelection() { selectedIds.value = [] }

  function exportExcel() {
    const params = {
      keyword: searchKeyword.value.trim(),
      low_stock: lowStockOnly.value ? '1' : '',
      location: locationFilter.value,
      specification: specificationFilter.value.join(','),
      quality_status: qualityStatusFilter.value,
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    }
    window.open(api.domains.inventory.inventoryExportUrl(params), '_blank')
  }

  function exportCsv() {
    const params = {
      keyword: searchKeyword.value.trim(),
      low_stock: lowStockOnly.value ? '1' : '',
      location: locationFilter.value,
      specification: specificationFilter.value.join(','),
      quality_status: qualityStatusFilter.value,
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    }
    if (selectedIds.value.length) params.inventory_id = selectedIds.value.join(',')
    window.open(api.domains.inventory.inventoryExportCsvUrl(params), '_blank')
  }

  function exportSelected() {
    if (!selectedIds.value.length) return
    if (!window.confirm(`确认导出已选 ${selectedIds.value.length} 条库存吗？`)) return
    const params = {
      inventory_id: selectedIds.value.join(','),
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    }
    window.open(api.domains.inventory.inventoryExportUrl(params), '_blank')
  }

  async function doABC() {
    try {
      await api.domains.inventory.classifyABC()
      showToast('ABC 分类完成')
      await load()
    } catch (error) {
      showToast(error.message || 'ABC分类失败', 'error')
    }
  }

  async function loadTurnover() {
    showTurnover.value = true
    turnoverLoading.value = true
    try {
      const data = await api.domains.inventory.inventoryTurnover()
      turnoverData.value = data.items || []
    } catch (error) {
      showToast('加载周转数据失败', 'error')
    } finally {
      turnoverLoading.value = false
    }
  }

  async function doCount() {
    countLoading.value = true
    try {
      let data = await api.domains.inventory.countStatus()
      if (!data.task || data.task.status === 'posted') {
        if (!confirm('确定创建新的盘点任务吗？')) return
        data = await api.domains.inventory.createCountTask()
        showToast('盘点任务已创建')
      }
      applyCountTask(data)
      showCount.value = true
    } catch (error) {
      showToast(error.message || '加载盘点任务失败', 'error')
    } finally {
      countLoading.value = false
    }
  }

  function applyCountTask(data) {
    countTask.value = data.task || null
    countItems.value = (data.items || []).map((item) => ({
      ...item,
      actual_qty: item.actual_quantity == null ? item.book_quantity : item.actual_quantity,
    }))
  }

  async function saveCountItem(item) {
    try {
      await api.domains.inventory.submitCount(item.inventory_id, {
        task_id: countTask.value.id,
        actual_qty: Number(item.actual_qty),
        remark: item.remark || '',
      })
      const data = await api.domains.inventory.countStatus(countTask.value.id)
      applyCountTask(data)
      showToast('盘点数量已记录')
    } catch (error) {
      showToast(error.message || '盘点录入失败', 'error')
    }
  }

  async function approveCount() {
    if (!countTask.value || !confirm('确定审批并过账全部盘点差异吗？')) return
    countLoading.value = true
    try {
      const data = await api.domains.inventory.approveCountTask(countTask.value.id)
      applyCountTask(data)
      showToast('盘点差异已过账')
      await load()
    } catch (error) {
      showToast(error.message || '盘点审批失败', 'error')
    } finally {
      countLoading.value = false
    }
  }

  async function loadLocations() {
    try {
      const data = await api.domains.inventory.listLocations()
      locations.value = (data.locations || []).map((row) => row.location)
    } catch (error) {
      // noop
    }
  }

  async function loadFilterOptions() {
    try {
      const data = await api.domains.inventory.inventoryFilterOptions({ view: 'order' })
      filterOptions.value = data
      locations.value = (data.locations || []).map((row) => row.value || row.location).filter(Boolean)
    } catch (_) {
      // Keep the legacy location endpoint as a fallback.
      await loadLocations()
    }
  }

  async function loadLogs(inventoryId) {
    showLogs.value = true
    logsLoading.value = true
    try {
      const params = inventoryId ? { inventory_id: inventoryId } : {}
      const data = await api.domains.inventory.inventoryLogs(params)
      logs.value = data.logs || []
    } catch (error) {
      showToast(error.message || '加载流水失败', 'error')
    } finally {
      logsLoading.value = false
    }
  }

  function openAdd() {
    form.value = {
      product_model: '',
      product_name: '',
      specification: '',
      quantity: 0,
      safe_stock: 0,
      location: '',
      unit: '件',
      remark: '',
      order_id: '',
    }
    modalEdit.value = false
    modalId.value = null
    showModal.value = true
  }

  function openEdit(item) {
    form.value = {
      product_model: item.product_model || '',
      product_name: item.product_name || '',
      specification: item.specification || '',
      quantity: item.quantity || 0,
      safe_stock: item.safe_stock || 0,
      location: item.location || '',
      unit: item.unit || '件',
      remark: item.remark || '',
    }
    modalEdit.value = true
    modalId.value = item.id
    showModal.value = true
  }

  async function save() {
    if (!form.value.product_model.trim()) {
      showToast('请输入产品型号', 'error')
      return
    }
    try {
      const payload = { ...form.value }
      if (modalEdit.value) {
        delete payload.quantity
        delete payload.order_id
        await api.domains.inventory.updateInventory(modalId.value, payload)
        showToast('更新成功')
      } else {
        payload.order_id = payload.order_id ? Number(payload.order_id) : null
        await api.domains.inventory.createInventory(payload)
        showToast('创建成功')
      }
      showModal.value = false
      await load()
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    }
  }

  async function del(item) {
    let impactInfo = ''
    try {
      const result = await api.domains.inventory.inventoryImpact(item.id)
      if (result.warnings?.length) {
        impactInfo = '（' + result.warnings.join('；') + '）'
      }
    } catch (error) {
      // non-blocking
    }
    if (!confirm('确定停用库存 "' + item.product_model + '" 吗？' + impactInfo)) return
    try {
      await api.domains.inventory.deleteInventory(item.id)
      showToast('已停用')
      await load()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  function openMove(item, type) {
    moveTarget.value = item
    moveType.value = type
    moveQty.value = 1
    moveLotNo.value = ''
    moveSerialNo.value = ''
    showMoveModal.value = true
  }

  async function doMove() {
    const quantity = parseInt(moveQty.value)
    if (!quantity || quantity <= 0) {
      showToast('请输入有效数量', 'error')
      return
    }
    try {
      if (moveType.value === 'in') {
        const payload = {
          inventory_id: moveTarget.value.id, quantity, remark: '手动入库',
          lot_no: moveLotNo.value, serial_no: moveSerialNo.value,
        }
        if (moveOrderId.value) {
          payload.order_id = moveOrderId.value
          const order = orderOptions.value.find((item) => item.id == moveOrderId.value)
          if (order) payload.order_no = order.order_no
        }
        await api.domains.inventory.stockIn(payload)
        showToast('入库成功 +' + quantity)
      } else {
        await api.domains.inventory.stockOut({
          inventory_id: moveTarget.value.id, quantity, remark: '手动出库',
          lot_no: moveLotNo.value, serial_no: moveSerialNo.value,
        })
        showToast('出库成功 -' + quantity)
      }
      showMoveModal.value = false
      moveOrderId.value = ''
      await load()
    } catch (error) {
      showToast(error.message || '操作失败', 'error')
    }
  }

  async function loadOrders() {
    try {
      const data = await api.domains.orders.listOrders({ limit: 999 })
      orderOptions.value = data.orders || []
    } catch (error) {
      // noop
    }
  }

  onMounted(() => {
    load()
    loadOrders()
    loadFilterOptions()
  })
  onUnmounted(cancelPendingLoad)

  return {
    items,
    total,
    page,
    limit,
    orderOptions,
    loading,
    searchKeyword,
    lowStockOnly,
    locationFilter,
    locations,
    specificationFilter,
    qualityStatusFilter,
    filterOptions,
    filters,
    savedFilters,
    showLogs,
    logs,
    logsLoading,
    showTurnover,
    turnoverData,
    turnoverLoading,
    showCount,
    countLoading,
    countTask,
    countItems,
    showModal,
    modalEdit,
    form,
    showMoveModal,
    moveType,
    moveTarget,
    moveQty,
    moveOrderId,
    moveLotNo,
    moveSerialNo,
    stats,
    lowCount,
    totalQty,
    inventoryValue,
    canEdit,
    canDelete,
    canCreate,
    canExport,
    sortBy,
    sortDir,
    summaryLoading,
    visibleColumns,
    orderColumns: ORDER_COLUMNS,
    selectedIds,
    selectedCount,
    load,
    cancelPendingLoad,
    search,
    resetFilters,
    setFilter,
    clearFilter,
    saveFilter,
    applyFilter,
    removeFilterPreset,
    changePage,
    changeLimit,
    setSort,
    setVisibleColumns,
    resetVisibleColumns,
    toggleSelect,
    toggleSelectAll,
    clearSelection,
    loadStats,
    loadFilterOptions,
    exportExcel,
    exportCsv,
    exportSelected,
    doABC,
    loadTurnover,
    loadLocations,
    doCount,
    saveCountItem,
    approveCount,
    loadLogs,
    openAdd,
    openEdit,
    save,
    del,
    openMove,
    doMove,
  }
}
