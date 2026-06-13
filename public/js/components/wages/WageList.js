// WageList — 工资核算
import { ref, computed, onMounted, onBeforeUnmount } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'

export default {
  template: '#wage-list-template',
  setup() {
    const wages = ref([])
    const loading = ref(false)
    const dateFrom = ref('')
    const dateTo = ref('')
    const expandedId = ref(null)
    const includeRework = ref(false)
    const hideZero = ref(false)
    const page = ref(1)
    const limit = ref(50)
    const total = ref(0)
    let _refreshTimer = null

    const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))

    function fmtMoney(v) { return Number(v || 0).toFixed(2) }
    function fmtDate(s) { if (!s) return ''; const m = s.match(/^\d{4}-\d{2}-\d{2}/); return m ? m[0] : s }

    async function load(pg) {
      if (pg !== undefined) page.value = pg
      loading.value = true
      const params = []
      if (dateFrom.value) params.push('date_from=' + dateFrom.value)
      if (dateTo.value) params.push('date_to=' + dateTo.value)
      if (includeRework.value) params.push('include_rework=1')
      params.push('page=' + page.value)
      params.push('limit=' + limit.value)
      try {
        const r = await api.get('/api/wages?' + params.join('&'))
        wages.value = r.wages || []
        total.value = r.total || 0
      } catch (e) { showToast('加载失败', 'error') }
      finally { loading.value = false }
    }

    function toggle(id) { expandedId.value = expandedId.value === id ? null : id }

    const filteredWages = computed(() => {
      if (!hideZero.value) return wages.value
      return wages.value.filter(w => w.total_quantity > 0)
    })

    function grandTotal() {
      return filteredWages.value.reduce((s, w) => s + (w.total_wage || 0), 0)
    }

    function grandQty() {
      return filteredWages.value.reduce((s, w) => s + (w.total_quantity || 0), 0)
    }

    function exportCSV() {
      const rows = [['姓名', '工号', '日期', '订单号', '产品', '工序', '数量', '单价', '工资']]
      for (const w of filteredWages.value) {
        for (const d of (w.details || [])) {
          rows.push([w.employee_name, w.employee_no, fmtDate(d.date), d.order_no, d.product_name, d.process_name, d.quantity, fmtMoney(d.unit_price), fmtMoney(d.wage)])
        }
        rows.push([w.employee_name, w.employee_no, '', '', '', '小计', w.total_quantity, '', fmtMoney(w.total_wage)])
      }
      rows.push(['', '', '', '', '', '合计', grandQty(), '', fmtMoney(grandTotal())])
      const csv = '\uFEFF' + rows.map(r => r.map(c => {
        const s = String(c == null ? '' : c)
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
      }).join(',')).join('\n')
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = '工资明细_' + (dateFrom.value || '全部') + '_' + (dateTo.value || '全部') + '.csv'
      a.click(); URL.revokeObjectURL(url)
    }

    function prevPage() { if (page.value > 1) load(page.value - 1) }
    function nextPage() { if (page.value < totalPages.value) load(page.value + 1) }

    onMounted(() => { load(); _refreshTimer = setInterval(load, 60000) })
    onBeforeUnmount(() => { if (_refreshTimer) clearInterval(_refreshTimer) })

    return { wages, loading, dateFrom, dateTo, expandedId, includeRework, hideZero, page, limit, total, totalPages,
             fmtMoney, fmtDate, load, toggle, filteredWages, grandTotal, grandQty, exportCSV, prevPage, nextPage }
  }
}
