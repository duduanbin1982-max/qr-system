// InventoryList Component — 库存管理
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js'
import { showToast } from '../../store.js'
import { auth, can } from '../../auth.js'

export default {
  template: '#inventory-list-template',
  setup() {
    const items = ref([])
    const loading = ref(true)
    const searchKeyword = ref('')
    const lowStockOnly = ref(false)

    // 流水
    const showLogs = ref(false)
    const logs = ref([])
    const logsLoading = ref(false)

    // 模态框 - 新增/编辑
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ product_model:'', product_name:'', specification:'', quantity:0, safe_stock:0, location:'', unit:'件', remark:'' })

    // 出入库
    const showMoveModal = ref(false)
    const moveType = ref('in')
    const moveTarget = ref(null)
    const moveQty = ref(1)

    // 统计
    const lowCount = computed(() => items.value.filter(i => i.is_low).length)
    const totalQty = computed(() => items.value.reduce((s, i) => s + (i.quantity || 0), 0))
    const stats = ref({ total_items: 0, total_quantity: 0, low_stock: 0, today_in: 0, today_out: 0 })

    async function loadStats() {
      try { 
        const d = await api.inventoryStats()
        Object.assign(stats.value, d)
      } catch(e) { console.error('loadStats failed:', e) }
    }

    async function load() {
      loading.value = true
      try {
        const params = {}
        if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
        if (lowStockOnly.value) params.low_stock = '1'
        const d = await api.listInventory(Object.keys(params).length ? params : null)
        items.value = d.items || []
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }

    async function loadLogs(invId) {
      showLogs.value = true
      logsLoading.value = true
      try {
        const params = invId ? { inventory_id: invId } : {}
        const d = await api.inventoryLogs(params)
        logs.value = d.logs || []
      } catch(e) {
        showToast(e.message || '加载流水失败', 'error')
      } finally {
        logsLoading.value = false
      }
    }

    function openAdd() {
      form.value = { product_model:'', product_name:'', specification:'', quantity:0, safe_stock:0, location:'', unit:'件', remark:'' }
      modalEdit.value = false; modalId.value = null
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
        remark: item.remark || ''
      }
      modalEdit.value = true; modalId.value = item.id
      showModal.value = true
    }

    async function save() {
      if (!form.value.product_model.trim()) { showToast('请输入产品型号','error'); return }
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
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }

    async function del(item) {
      if (!confirm('确定删除库存 "' + item.product_model + '" 吗？')) return
      try {
        await api.deleteInventory(item.id)
        showToast('删除成功')
        await load()
        await loadStats()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }

    function openMove(item, type) {
      moveTarget.value = item
      moveType.value = type
      moveQty.value = 1
      showMoveModal.value = true
    }

    async function doMove() {
      const qty = parseInt(moveQty.value)
      if (!qty || qty <= 0) { showToast('请输入有效数量','error'); return }
      try {
        if (moveType.value === 'in') {
          await api.stockIn({ inventory_id: moveTarget.value.id, quantity: qty, remark: '手动入库' })
          showToast('入库成功 +' + qty)
        } else {
          await api.stockOut({ inventory_id: moveTarget.value.id, quantity: qty, remark: '手动出库' })
          showToast('出库成功 -' + qty)
        }
        showMoveModal.value = false
        await load()
        await loadStats()
      } catch(e) {
        showToast(e.message || '操作失败', 'error')
      }
    }

    onMounted(() => { load(); loadStats() })

    return {
      items, loading, searchKeyword, lowStockOnly, load,
      lowCount, totalQty, stats,
      showLogs, logs, logsLoading, loadLogs,
      showModal, modalEdit, form, openAdd, openEdit, save, del,
      showMoveModal, moveType, moveTarget, moveQty, openMove, doMove,
      auth, can
    }
  }
}
