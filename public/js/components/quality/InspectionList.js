// InspectionList — 质量检验
import { ref, onMounted } from '../../vendor/vue.esm.js'
import { api } from '../../api.js'
import { showToast } from '../../store.js'

const INSPECTION_TYPES = [
  { value: 'first_article', label: '首件检验' },
  { value: 'in_process', label: '过程检验' },
  { value: 'final', label: '终检' },
]
const DEFECT_CATEGORIES = ['尺寸超差', '外观缺陷', '材质问题', '焊接缺陷', '装配不良', '其他']
const RESULT_LABELS = { pass: '合格', fail: '不合格', partial: '部分合格', pending: '待检' }

export default {
  template: '#inspection-list-template',
  setup() {
    const items = ref([])
    const loading = ref(false)
    const stats = ref({ total: 0, today_count: 0, pass_count: 0, fail_count: 0 })
    const search = ref('')
    const filterType = ref('')
    const filterResult = ref('')
    const dateFrom = ref('')
    const dateTo = ref('')
    const page = ref(1)
    const total = ref(0)
    const perPage = 20
    const editing = ref(null)

    // Create/Edit modal
    const showModal = ref(false); const isEdit = ref(false)
    const form = ref({})
    const orders = ref([]); const processes = ref([])
    const orderSearch = ref(''); const processSearch = ref('')
    const orderDropdown = ref(false); const processDropdown = ref(false)

    function fmtDate(s) { if (!s) return ''; const m = s.match(/^\d{4}-\d{2}-\d{2}/); return m ? m[0] : s }
    function fmtDatetime(s) { if (!s) return ''; const m = s.match(/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}/); return m ? m[0] : s }
    function typeLabel(t) { const f = INSPECTION_TYPES.find(x => x.value === t); return f ? f.label : t }
    function resultLabel(r) { return RESULT_LABELS[r] || r }

    async function load(p = 1) {
      loading.value = true; page.value = p
      const params = []
      if (search.value) params.push('search=' + encodeURIComponent(search.value))
      if (filterType.value) params.push('type=' + filterType.value)
      if (filterResult.value) params.push('result=' + filterResult.value)
      if (dateFrom.value) params.push('from=' + dateFrom.value)
      if (dateTo.value) params.push('to=' + dateTo.value)
      params.push('page=' + p, 'per_page=' + perPage)
      try {
        const r = await api.get('/api/quality/inspections?' + params.join('&'))
        if (r.ok) { items.value = r.items; total.value = r.total }
      } catch (e) { showToast('加载失败', 'error') }
      finally { loading.value = false }
    }

    async function loadStats() {
      try { const r = await api.get('/api/quality/inspections/stats'); if (r.ok) stats.value = r } catch (e) {}
    }

    async function searchOrders() {
      if (!orderSearch.value) { orders.value = []; orderDropdown.value = false; return }
      try {
        const r = await api.get('/api/orders?keyword=' + encodeURIComponent(orderSearch.value) + '&limit=10')
        if (r.ok) { orders.value = r.orders || []; orderDropdown.value = orders.value.length > 0 }
      } catch (e) {}
    }

    async function searchProcesses() {
      if (!processSearch.value) { processes.value = []; processDropdown.value = false; return }
      try {
        const r = await api.get('/api/processes')
        if (r.ok) {
          const q = processSearch.value.toLowerCase()
          processes.value = (r.processes || []).filter(p => p.status === 'active' && (!q || (p.process_name || '').toLowerCase().includes(q)))
          processDropdown.value = processes.value.length > 0
        }
      } catch (e) {}
    }

    function selectOrder(o) { form.value.order_id = o.id; orderSearch.value = o.order_no + ' ' + (o.product_name || ''); orderDropdown.value = false }
    function selectProcess(p) { form.value.process_id = p.id; processSearch.value = p.process_name; processDropdown.value = false }

    function autoCalcQty() {
      form.value.quantity_checked = (form.value.quantity_passed || 0) + (form.value.quantity_failed || 0)
    }

    function openCreate() {
      isEdit.value = false
      form.value = { order_id: null, process_id: null, inspection_type: 'first_article', quantity_checked: 0, quantity_passed: 0, quantity_failed: 0, defect_category: '', defect_quantity: 0, notes: '', inspected_at: '' }
      orderSearch.value = ''; processSearch.value = ''; orders.value = []; processes.value = []
      showModal.value = true
    }

    function openEdit(item) {
      isEdit.value = true
      form.value = { ...item }
      orderSearch.value = item.order_no + ' ' + (item.product_name || '')
      processSearch.value = item.process_name || ''
      showModal.value = true
    }

    async function doSave() {
      if (!form.value.order_id || !form.value.process_id) { showToast('请选择订单和工序', 'error'); return }
      autoCalcQty()
      try {
        let r
        if (isEdit.value) {
          const payload = { inspection_type: form.value.inspection_type, quantity_checked: form.value.quantity_checked, quantity_passed: form.value.quantity_passed, quantity_failed: form.value.quantity_failed, defect_category: form.value.defect_category || '', defect_quantity: form.value.defect_quantity || 0, notes: form.value.notes, inspected_at: form.value.inspected_at }
          r = await api.put('/api/quality/inspections/' + form.value.id, payload)
        } else {
          r = await api.post('/api/quality/inspections', form.value)
        }
        if (r.ok) { showToast(isEdit.value ? '已更新' : '已创建'); showModal.value = false; load(page.value); loadStats() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('保存失败', 'error') }
    }

    async function doDelete(item) {
      if (!confirm('确认删除检验记录？')) return
      try {
        const r = await api.del('/api/quality/inspections/' + item.id)
        if (r.ok) { showToast('已删除'); load(page.value); loadStats() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('删除失败', 'error') }
    }

    function applyFilter() { page.value = 1; load() }

    // Pareto
    const pareto = ref({ items: [], grand_total: 0 })

    async function loadPareto() {
      try {
        const params = []
        if (dateFrom.value) params.push('from=' + dateFrom.value)
        if (dateTo.value) params.push('to=' + dateTo.value)
        const r = await api.get('/api/quality/defect-pareto?' + params.join('&'))
        if (r.ok) pareto.value = r
      } catch (e) {}
    }

    onMounted(() => { load(); loadStats(); loadPareto() })

    return { items, loading, stats, search, filterType, filterResult, dateFrom, dateTo, page, total, perPage, editing,
      showModal, isEdit, form, orders, processes, orderSearch, processSearch, orderDropdown, processDropdown,
      DEFECT_CATEGORIES, pareto,
      fmtDate, fmtDatetime, typeLabel, resultLabel,
      load, loadStats, searchOrders, searchProcesses, selectOrder, selectProcess, autoCalcQty, openCreate, openEdit, doSave, doDelete, applyFilter, loadPareto }
  }
}
