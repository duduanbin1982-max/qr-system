// ReworkList — 返工管理
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { can } from '../../auth.js'

export default {
  template: '#rework-list-template',
  setup() {
    const items = ref([])
    const loading = ref(false)
    const statusFilter = ref('pending')
    const search = ref('')
    const stats = ref({ pending_count:0, pending_qty:0, today_count:0, today_qty:0, today_done:0, today_done_qty:0 })
    const editing = ref(null)
    const dateFrom = ref('')
    const dateTo = ref('')
    const page = ref(1)
    const total = ref(0)
    const perPage = 20

    // RBAC
    const canEdit   = computed(() => can('rework:edit'))
    const canDelete = computed(() => can('rework:delete'))
    const canCreate = computed(() => can('rework:create'))

    function fmtDate(s) {
      if (!s) return ''
      const m = s.match(/^\d{4}-\d{2}-\d{2}/)
      return m ? m[0] : s
    }
    function fmtDatetime(s) {
      if (!s) return ''
      const m = s.match(/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}/)
      return m ? m[0] : s
    }

    async function load(p = 1) {
      loading.value = true; page.value = p
      const params = []
      if (statusFilter.value) params.push('status=' + statusFilter.value)
      if (search.value) params.push('search=' + encodeURIComponent(search.value))
      if (dateFrom.value) params.push('from=' + dateFrom.value)
      if (dateTo.value) params.push('to=' + dateTo.value)
      params.push('page=' + p, 'per_page=' + perPage)
      try {
        const r = await api.get('/api/rework?' + params.join('&'))
        if (r.ok) { items.value = r.items; total.value = r.total }
      } catch (e) { showToast('加载失败', 'error') }
      finally { loading.value = false }
    }

    async function loadStats() {
      try { const r = await api.get('/api/rework/stats'); if (r.ok) stats.value = r } catch (e) {}
    }

    async function complete(item) {
      if (!confirm('确认完成返工 ' + item.order_no + '？')) return
      try {
        const r = await api.post('/api/rework/' + item.id + '/complete', { reason: item.reason })
        if (r.ok) { showToast('返工完成'); load(page.value); loadStats() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('操作失败', 'error') }
    }

    function startEdit(item) { editing.value = item.id }
    function cancelEdit() { editing.value = null }

    async function saveEdit(item) {
      try {
        const r = await api.put('/api/rework/' + item.id, { reason: item.reason })
        if (r.ok) { showToast('已更新'); editing.value = null }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('保存失败', 'error') }
    }

    function switchTab(status) { statusFilter.value = status; search.value = ''; page.value = 1; load() }
    function applyFilter() { page.value = 1; load() }

    onMounted(() => { load(); loadStats() })

    return { items, loading, statusFilter, search, stats, editing, dateFrom, dateTo, page, total, perPage, fmtDate, fmtDatetime, load, loadStats, complete, startEdit, cancelEdit, saveEdit, switchTab, applyFilter, canEdit, canDelete, canCreate }
  }
}
