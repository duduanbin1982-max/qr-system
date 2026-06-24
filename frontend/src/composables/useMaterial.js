import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

let _instance = null

export function useMaterial() {
  if (_instance) return _instance

  const materials = ref([])
  const logs = ref([])
  const suppliers = ref([])
  const loading = ref(true)
  const showForm = ref(false)
  const showStock = ref(false)
  const showConsume = ref(false)
  const editing = ref(null)
  const selectedMaterial = ref(null)
  const showDetail = ref(false)
  const detailConsumptions = ref([])
  const trendChart = ref(null)
  const searchText = ref('')
  const materialTypeFilter = ref('')
  const showSupplierForm = ref(false)
  const supplierForm = ref({ name: '', contact: '', phone: '' })

  const form = ref({ name: '', spec: '', unit: '件', quantity: 0, unit_price: 0, safe_stock: 0, location: '', supplier_id: null, material_type: '', remark: '' })
  const stockForm = ref({ type: 'in', quantity: 0, remark: '', operator_name: '' })

  // Consumption state
  const consumptions = ref([])
  const consumeForm = ref({ order_id: null, process_id: null, quantity: 0, notes: '', operator_name: '' })
  const orderSearch = ref('')
  const orderResults = ref([])
  const orderDropdown = ref(false)

  const lowStock = computed(() => materials.value.filter(m => m.quantity <= (m.safe_stock || 0)))
  
  const abcRanks = computed(() => {
    const sorted = [...materials.value]
      .map(m => ({ id: m.id, val: (m.quantity || 0) * (m.unit_price || 0) }))
      .sort((a, b) => b.val - a.val)
    const totalVal = sorted.reduce((s, x) => s + x.val, 0)
    const map = {}
    let cumulative = 0
    sorted.forEach((item) => {
      cumulative += item.val
      const pct = totalVal > 0 ? cumulative / totalVal : 0
      if (pct <= 0.70) map[item.id] = "A"
      else if (pct <= 0.90) map[item.id] = "B"
      else map[item.id] = "C"
    })
    return map
  })

  const totalInventoryValue = computed(() => {
    const total = materials.value.reduce((sum, m) => sum + (m.quantity || 0) * (m.unit_price || 0), 0)
    return total.toFixed(2)
  })

  const materialTypeOptions = computed(() => {
    const types = new Set()
    materials.value.forEach(m => { if (m.material_type) types.add(m.material_type) })
    return [...types].sort()
  })

  const filteredMaterials = computed(() => {
    let arr = materials.value
    if (searchText.value) {
      const q = searchText.value.toLowerCase()
      arr = arr.filter(m =>
        (m.name || '').toLowerCase().includes(q) ||
        (m.spec || '').toLowerCase().includes(q) ||
        (m.location || '').toLowerCase().includes(q)
      )
    }
    if (materialTypeFilter.value) {
      arr = arr.filter(m => m.material_type === materialTypeFilter.value)
    }
    return arr
  })

  // RBAC
  const canEdit = computed(() => can('materials:manage'))
  const canDelete = computed(() => can('materials:manage'))
  const canCreate = computed(() => can('materials:manage'))

  // Dialog low stock warning computed properties
  const stockGap = computed(() => (form.value.quantity || 0) - (form.value.safe_stock || 0))
  const stockStatus = computed(() => {
    const gap = stockGap.value
    if (gap > 0) return { icon: 'passed', cls: 'stock-ok', text: 'Stock OK' }
    if (gap === 0) return { icon: 'warn', cls: 'stock-warn', text: 'Stock tight' }
    return { icon: 'danger', cls: 'stock-danger', text: 'Below safety by ' + Math.abs(gap) }
  })
  const showStockWarning = computed(() => editing.value && stockGap.value < 0)

  async function load() {
    loading.value = true
    try {
      const d = await api.listMaterials()
      materials.value = d.materials || []
    } catch (e) { showToast(e.message, 'error') }
    finally { loading.value = false }
  }

  function openCreate() {
    editing.value = null
    form.value = { name: '', spec: '', unit: '件', quantity: 0, unit_price: 0, safe_stock: 0, location: '', supplier_id: null, material_type: '', remark: '' }
    showForm.value = true
  }

  function openEdit(m) {
    editing.value = m.id
    const f = { ...m }
    if (f.supplier_id === '' || f.supplier_id === 0) f.supplier_id = null
    form.value = f
    showForm.value = true
  }

  async function save() {
    if (!form.value.name.trim()) { showToast('名称必填', 'error'); return }
    try {
      const payload = { ...form.value }
      for (const k of ['quantity', 'unit_price', 'safe_stock']) {
        if (payload[k] == null || payload[k] === '' || isNaN(payload[k])) payload[k] = 0
      }
      if (payload.supplier_id === '' || payload.supplier_id === 0) payload.supplier_id = null
      if (editing.value) {
        await api.updateMaterial(editing.value, payload)
      } else {
        await api.createMaterial(payload)
      }
      showForm.value = false
      showToast('保存成功')
      await load()
    } catch (e) { showToast(e.message || '保存失败', 'error') }
  }

  async function remove(m) {
    if (!confirm('确定删除物料「' + m.name + '」？')) return
    try {
      const res = await api.getMaterialImpact(m.id)
      if (res && (res.refs || 0) > 0) {
        showToast('该物料正在被 ' + res.refs + ' 个地方引用，无法删除', 'error')
        return
      }
      await api.deleteMaterial(m.id)
      showToast('已删除')
      await load()
    } catch (e) { showToast(e.message || '删除失败', 'error') }
  }

  function openStock(m) {
    selectedMaterial.value = m
    stockForm.value = { type: 'in', quantity: 0, remark: '', operator_name: '' }
    showStock.value = true
  }

  async function doStock() {
    if (stockForm.value.quantity <= 0) { showToast('数量必须大于0', 'error'); return }
    try {
      await api.materialStockChange(selectedMaterial.value.id, stockForm.value)
      showStock.value = false
      showToast('操作成功')
      await load()
    } catch (e) { showToast(e.message, 'error') }
  }

  async function viewLogs(m) {
    selectedMaterial.value = m
    try {
      const d = await api.getMaterialLogs(m.id)
      logs.value = d.logs || []
    } catch (e) { logs.value = [] }
  }

  async function openConsume(m) {
    selectedMaterial.value = m
    showConsume.value = true
    consumeForm.value = { order_id: null, process_id: null, quantity: 0, notes: '', operator_name: '' }
    try {
      const d = await api.getMaterialConsumptions(m.id)
      consumptions.value = d.consumptions || []
    } catch (e) { consumptions.value = [] }
  }

  async function searchOrders() {
    if (!orderSearch.value.trim()) { orderResults.value = []; return }
    try {
      const r = await api.get('/api/orders?keyword=' + encodeURIComponent(orderSearch.value) + '&limit=8')
      orderResults.value = r.orders || []
      orderDropdown.value = true
    } catch (e) { orderResults.value = [] }
  }

  function selectOrder(o) {
    consumeForm.value.order_id = o.id
    orderSearch.value = o.order_no + ' ' + (o.product_name || '')
    orderDropdown.value = false
  }

  function fmtDate(s) { if (!s) return ''; const m = s.match(/^\d{4}-\d{2}-\d{2}/); return m ? m[0] : s }

  async function doConsume() {
    if (consumeForm.value.quantity <= 0) { showToast('数量必须大于0', 'error'); return }
    try {
      await api.createMaterialConsumption(selectedMaterial.value.id, consumeForm.value)
      showToast('消耗已记录')
      openConsume(selectedMaterial.value)
      await load()
    } catch (e) { showToast('操作失败', 'error') }
  }

  async function undoConsume(c) {
    if (!confirm('撤销消耗将恢复库存，确定？')) return
    try {
      await api.deleteMaterialConsumption(c.id)
      showToast('已撤销')
      openConsume(selectedMaterial.value)
      await load()
    } catch (e) { showToast('操作失败', 'error') }
  }

  async function loadSuppliers() {
    try { const d = await api.listSuppliers(); suppliers.value = d.suppliers || [] } catch (e) {}
  }

  function openSupplierAdd() {
    supplierForm.value = { name: '', contact: '', phone: '' }
    showSupplierForm.value = true
  }

  async function addSupplier() {
    if (!supplierForm.value.name.trim()) { showToast('供应商名称必填', 'error'); return }
    try {
      const r = await api.createSupplier(supplierForm.value)
      showSupplierForm.value = false
      await loadSuppliers()
      if (r.id) {
        form.value.supplier_id = r.id
      } else if (suppliers.value.length > 0) {
        form.value.supplier_id = suppliers.value[suppliers.value.length - 1].id
      }
      showToast('供应商已添加')
    } catch (e) { showToast(e.message || '添加失败', 'error') }
  }

  async function deleteSupplier(s) {
    if (!confirm('确定删除供应商「' + s.name + '」？如有物料关联将无法删除。')) return
    try {
      await api.deleteSupplier(s.id)
      await loadSuppliers()
      showToast('供应商已删除')
    } catch (e) { showToast(e.message || '删除失败', 'error') }
  }

  function getAbcClass(m) {
    return abcRanks.value[m.id] || "C"
  }

  async function openDetail(m) {
    selectedMaterial.value = m
    showDetail.value = true
    try {
      const d = await api.get("/api/materials/" + m.id + "/consumptions")
      detailConsumptions.value = (d.consumptions || []).slice(0, 20)
    } catch (e) { detailConsumptions.value = [] }
    setTimeout(() => renderTrendChart(), 200)
  }

  function renderTrendChart() {
    if (!trendChart.value) return
    const ctx = trendChart.value.getContext("2d")
    if (trendChart.value._chart) trendChart.value._chart.destroy()
    const data = detailConsumptions.value
    if (!data.length) return
    const byDate = {}
    data.forEach(c => {
      const d = (c.created_at || "").slice(0, 10)
      if (!byDate[d]) byDate[d] = 0
      byDate[d] += Number(c.quantity || 0)
    })
    const dates = Object.keys(byDate).sort()
    const amounts = dates.map(d => byDate[d])
    if (typeof Chart === 'undefined') return
    trendChart.value._chart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: dates,
        datasets: [{
          label: "消耗量",
          data: amounts,
          backgroundColor: "rgba(239,68,68,0.6)",
          borderColor: "rgba(239,68,68,1)",
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "消耗数量" } },
          x: { title: { display: true, text: "日期" } }
        }
      }
    })
  }

  onMounted(() => { load(); loadSuppliers() })

  _instance = {
    materials, logs, suppliers, loading, showForm, showStock, showConsume, editing, selectedMaterial,
    form, stockForm, lowStock, searchText,
    consumptions, consumeForm, orderSearch, orderResults, orderDropdown,
    openCreate, openEdit, save, remove, openStock, doStock, viewLogs,
    openConsume, searchOrders, selectOrder, fmtDate, doConsume, undoConsume,
    showSupplierForm, supplierForm, openSupplierAdd, addSupplier, deleteSupplier,
    abcRanks, getAbcClass,
    showDetail, detailConsumptions, trendChart, openDetail, renderTrendChart,
    canEdit, canDelete, canCreate, filteredMaterials, stockGap, stockStatus, showStockWarning,
    totalInventoryValue, materialTypeFilter, materialTypeOptions,
  }
  return _instance
}
