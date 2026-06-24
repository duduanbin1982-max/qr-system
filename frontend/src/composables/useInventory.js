import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export function useInventory() {
  const items = ref([])
  const orderOptions = ref([])
  const loading = ref(true)
  const searchKeyword = ref('')
  const lowStockOnly = ref(false)
  const locationFilter = ref('')
  const locations = ref([])

  const showLogs = ref(false)
  const logs = ref([])
  const logsLoading = ref(false)

  const showTurnover = ref(false)
  const turnoverData = ref([])
  const turnoverLoading = ref(false)

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

  const stats = ref({ total_items: 0, total_quantity: 0, low_stock: 0, today_in: 0, today_out: 0 })
  const lowCount = computed(() => stats.value.low_stock || items.value.filter((item) => item.is_low).length)
  const totalQty = computed(() => stats.value.total_quantity || items.value.reduce((sum, item) => sum + (item.quantity || 0), 0))
  const inventoryValue = computed(() => items.value.reduce((sum, item) => sum + (item.price || 0) * (item.quantity || 0), 0))

  const canEdit = computed(() => can('inventory:edit'))
  const canDelete = computed(() => can('inventory:delete'))
  const canCreate = computed(() => can('inventory:create'))

  async function loadStats() {
    try {
      const data = await api.inventoryStats()
      Object.assign(stats.value, data)
    } catch (error) {
      // noop
    }
  }

  async function load() {
    loading.value = true
    try {
      const params = {}
      if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
      if (lowStockOnly.value) params.low_stock = '1'
      if (locationFilter.value) params.location = locationFilter.value
      const data = await api.listInventory(Object.keys(params).length ? params : null)
      items.value = data.items || []
    } catch (error) {
      showToast(error.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  function exportExcel() {
    window.open('/api/inventory/export', '_blank')
  }

  async function doABC() {
    try {
      await api.classifyABC()
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
      const data = await api.inventoryTurnover()
      turnoverData.value = data.data || []
    } catch (error) {
      showToast('加载周转数据失败', 'error')
    } finally {
      turnoverLoading.value = false
    }
  }

  async function doCount() {
    if (!confirm('确定创建盘点任务吗？')) return
    try {
      await api.createCountTask()
      showToast('盘点任务已创建')
    } catch (error) {
      showToast(error.message || '创建失败', 'error')
    }
  }

  async function loadLocations() {
    try {
      const data = await api.listLocations()
      locations.value = data.locations || []
    } catch (error) {
      // noop
    }
  }

  async function loadLogs(inventoryId) {
    showLogs.value = true
    logsLoading.value = true
    try {
      const params = inventoryId ? { inventory_id: inventoryId } : {}
      const data = await api.inventoryLogs(params)
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
      if (modalEdit.value) {
        await api.updateInventory(modalId.value, form.value)
        showToast('更新成功')
      } else {
        await api.createInventory(form.value)
        showToast('创建成功')
      }
      showModal.value = false
      await load()
      await loadStats()
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    }
  }

  async function del(item) {
    let impactInfo = ''
    try {
      const result = await api.inventoryImpact(item.id)
      if (result.log_count > 0) {
        impactInfo = '（将同步删除 ' + result.log_count + ' 条流水记录）'
      }
    } catch (error) {
      // non-blocking
    }
    if (!confirm('确定删除库存 "' + item.product_model + '" 吗？' + impactInfo)) return
    try {
      await api.deleteInventory(item.id)
      showToast('删除成功')
      await load()
      await loadStats()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  function openMove(item, type) {
    moveTarget.value = item
    moveType.value = type
    moveQty.value = 1
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
        const payload = { inventory_id: moveTarget.value.id, quantity, remark: '手动入库' }
        if (moveOrderId.value) {
          payload.order_id = moveOrderId.value
          const order = orderOptions.value.find((item) => item.id == moveOrderId.value)
          if (order) payload.order_no = order.order_no
        }
        await api.stockIn(payload)
        showToast('入库成功 +' + quantity)
      } else {
        await api.stockOut({ inventory_id: moveTarget.value.id, quantity, remark: '手动出库' })
        showToast('出库成功 -' + quantity)
      }
      showMoveModal.value = false
      moveOrderId.value = ''
      await load()
      await loadStats()
    } catch (error) {
      showToast(error.message || '操作失败', 'error')
    }
  }

  async function loadOrders() {
    try {
      const data = await api.listOrders({ limit: 999 })
      orderOptions.value = data.orders || []
    } catch (error) {
      // noop
    }
  }

  onMounted(() => {
    load()
    loadStats()
    loadOrders()
    loadLocations()
  })

  return {
    items,
    orderOptions,
    loading,
    searchKeyword,
    lowStockOnly,
    locationFilter,
    locations,
    showLogs,
    logs,
    logsLoading,
    showTurnover,
    turnoverData,
    turnoverLoading,
    showModal,
    modalEdit,
    form,
    showMoveModal,
    moveType,
    moveTarget,
    moveQty,
    moveOrderId,
    stats,
    lowCount,
    totalQty,
    inventoryValue,
    canEdit,
    canDelete,
    canCreate,
    load,
    exportExcel,
    doABC,
    loadTurnover,
    doCount,
    loadLogs,
    openAdd,
    openEdit,
    save,
    del,
    openMove,
    doMove,
  }
}
