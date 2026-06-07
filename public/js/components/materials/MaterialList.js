// MaterialList Component — 物料管理
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { can } from '../../auth.js?v=56'

export default {
  template: '#material-list-template',
  setup() {
    const materials = ref([])
    const logs = ref([])
    const suppliers = ref([])
    const loading = ref(true)
    const showForm = ref(false)
    const showStock = ref(false)
    const showConsume = ref(false)
    const editing = ref(null)
    const selectedMaterial = ref(null)
    const searchText = ref('')

    const form = ref({ name: '', spec: '', unit: '件', quantity: 0, unit_price: 0, safe_stock: 0, location: '', remark: '' })
    const stockForm = ref({ type: 'in', quantity: 0, remark: '', operator_name: '' })

    // Consumption state
    const consumptions = ref([])
    const consumeForm = ref({ order_id: null, process_id: null, quantity: 0, notes: '', operator_name: '' })
    const orderSearch = ref('')
    const orderResults = ref([])
    const orderDropdown = ref(false)

    const lowStock = computed(() => materials.value.filter(m => m.quantity <= (m.safe_stock || 0)))

    // RBAC
    const canEdit   = computed(() => can('materials:edit'))
    const canDelete = computed(() => can('materials:delete'))
    const canCreate = computed(() => can('materials:create'))

    async function load() {
      loading.value = true
      try {
        const d = await api.get('/api/materials')
        materials.value = d.materials || []
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    function openCreate() {
      editing.value = null
      form.value = { name: '', spec: '', unit: '件', quantity: 0, unit_price: 0, safe_stock: 0, location: '', supplier_id: null, remark: '' }
      showForm.value = true
    }

    function openEdit(m) {
      editing.value = m.id
      form.value = { ...m }
      showForm.value = true
    }

    async function save() {
      if (!form.value.name.trim()) { showToast('名称必填', 'error'); return }
      try {
        if (editing.value) await api.put('/api/materials/' + editing.value, form.value)
        else await api.post('/api/materials', form.value)
        showForm.value = false
        await load()
        showToast(editing.value ? '已更新' : '已创建')
      } catch (e) { showToast(e.message, 'error') }
    }

    async function remove(m) {
      if (!confirm('确定删除物料「' + m.name + '」？')) return
      try {
        await api.del('/api/materials/' + m.id)
        await load()
        showToast('已删除')
      } catch (e) { showToast(e.message, 'error') }
    }

    function openStock(m) {
      selectedMaterial.value = m
      stockForm.value = { type: 'in', quantity: 0, remark: '', operator_name: '' }
      showStock.value = true
    }

    async function doStock() {
      if (stockForm.value.quantity <= 0) { showToast('数量必须大于0', 'error'); return }
      try {
        await api.post('/api/materials/' + selectedMaterial.value.id + '/stock', stockForm.value)
        showStock.value = false
        await load()
        showToast(stockForm.value.type === 'in' ? '已入库' : '已出库')
      } catch (e) { showToast(e.message, 'error') }
    }

    async function viewLogs(m) {
      selectedMaterial.value = m
      try {
        const d = await api.get('/api/materials/' + m.id + '/logs')
        logs.value = d.logs || []
      } catch (e) { showToast(e.message, 'error') }
    }

    // ===== Consumption =====
    async function openConsume(m) {
      selectedMaterial.value = m
      consumeForm.value = { order_id: null, process_id: null, quantity: 0, notes: '', operator_name: '' }
      orderSearch.value = ''; orderResults.value = []
      try {
        const d = await api.get('/api/materials/' + m.id + '/consumptions')
        consumptions.value = d.consumptions || []
      } catch (e) { consumptions.value = [] }
      showConsume.value = true
    }

    async function searchOrders() {
      if (!orderSearch.value) { orderResults.value = []; orderDropdown.value = false; return }
      try {
        const r = await api.get('/api/orders?keyword=' + encodeURIComponent(orderSearch.value) + '&limit=8')
        if (r.ok) { orderResults.value = r.orders || []; orderDropdown.value = orderResults.value.length > 0 }
      } catch (e) {}
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
        const r = await api.post('/api/materials/' + selectedMaterial.value.id + '/consumptions', consumeForm.value)
        if (r.ok) { showToast('消耗已记录'); openConsume(selectedMaterial.value); await load() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('操作失败', 'error') }
    }

    async function undoConsume(c) {
      if (!confirm('撤销消耗将恢复库存，确定？')) return
      try {
        const r = await api.del('/api/materials/consumptions/' + c.id)
        if (r.ok) { showToast('已撤销'); openConsume(selectedMaterial.value); await load() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('操作失败', 'error') }
    }

    async function loadSuppliers() {
      try { const d = await api.get('/api/suppliers'); suppliers.value = d.suppliers || [] } catch (e) {}
    }

    onMounted(() => { load(); loadSuppliers() })

    return {
      materials, logs, suppliers, loading, showForm, showStock, showConsume, editing, selectedMaterial,
      form, stockForm, lowStock, searchText,
      consumptions, consumeForm, orderSearch, orderResults, orderDropdown,
      openCreate, openEdit, save, remove, openStock, doStock, viewLogs,
      openConsume, searchOrders, selectOrder, fmtDate, doConsume, undoConsume,
      canEdit, canDelete, canCreate,
    }
  }
}
