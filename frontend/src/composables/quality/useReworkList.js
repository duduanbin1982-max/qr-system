import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export function useReworkList() {
  const items = ref([])
  const loading = ref(false)
  const statusFilter = ref('pending')
  const search = ref('')
  const filterWorker = ref('')
  const filterProcess = ref('')
  const workers = ref([])
  const processes = ref([])
  const selectedIds = ref([])
  const showBatchModal = ref(false)
  const batchReason = ref('')
  const batchResult = ref('ok')
  const batchErrors = ref([])
  const batchSubmitting = ref(false)
  const stats = ref({ pending_count:0, pending_qty:0, today_count:0, today_qty:0, today_done:0, today_done_qty:0 })
  const editing = ref(null)
  const editReason = ref('')
  const editSubmitting = ref(false)
  const dateFrom = ref('')
  const dateTo = ref('')
  const page = ref(1)
  const total = ref(0)
  const perPage = 20

  // RBAC
  const canEdit   = computed(() => can('rework:edit'))
  const allSelected = computed(() => {
    return items.value.length > 0 && items.value.every(it => selectedIds.value.includes(it.id))
  })

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
  function isOverdue(it) {
    if (!it.created_at || it.status !== 'pending') return false
    const created = new Date(it.created_at.replace(' ', 'T'))
    const now = new Date()
    return (now - created) > 24 * 60 * 60 * 1000
  }
  function overdueHours(it) {
    if (!it.created_at) return 0
    const created = new Date(it.created_at.replace(' ', 'T'))
    const now = new Date()
    return Math.round((now - created) / (60 * 60 * 1000))
  }

  let loadRequestId = 0
  async function load(p = 1) {
    const requestId = ++loadRequestId
    loading.value = true
    page.value = p
    try {
      const r = await api.domains.rework.listRework({status: statusFilter.value || undefined, search: search.value || undefined, from: dateFrom.value || undefined, to: dateTo.value || undefined, worker_id: filterWorker.value || undefined, process_id: filterProcess.value || undefined, page: p, per_page: perPage})
      if (requestId === loadRequestId && r.ok) {
        items.value = r.items
        total.value = r.total
      }
    } catch (e) {
      if (requestId === loadRequestId) showToast(e.message || '加载失败', 'error')
    } finally {
      if (requestId === loadRequestId) loading.value = false
    }
  }

  async function loadStats() {
    try { const r = await api.domains.rework.reworkStats(); if (r && r.ok) stats.value = r }
    catch (e) { console.warn('Rework stats load failed:', e) }
  }

  const completingItem = ref(null)
  const completeResult = ref('ok')
  const completeResultRemark = ref('')
  const completeSubmitting = ref(false)

  function openComplete(item) {
    completingItem.value = item
    completeResult.value = 'ok'
    completeResultRemark.value = ''
  }
  function closeComplete() { completingItem.value = null }

  async function doComplete() {
    const item = completingItem.value
    if (!item || completeSubmitting.value) return
    completeSubmitting.value = true
    try {
      const d = await api.domains.rework.completeRework(item.id, {
        reason: item.reason,
        result: completeResult.value,
        result_remark: completeResultRemark.value
      })
      if (d.ok) {
        showToast('返工完成')
        completingItem.value = null
        await Promise.all([load(page.value), loadStats()])
      }
      else showToast(d.error || '失败', 'error')
    } catch (e) {
      showToast(e.message || '操作失败', 'error')
    } finally {
      completeSubmitting.value = false
    }
  }

  function startEdit(item) {
    editing.value = item.id
    editReason.value = item.reason || ''
  }
  function cancelEdit() {
    editing.value = null
    editReason.value = ''
  }

  async function saveEdit(item) {
    if (editSubmitting.value) return
    editSubmitting.value = true
    try {
      const r = await api.domains.rework.updateRework(item.id, { reason: editReason.value })
      if (r.ok) {
        item.reason = editReason.value.trim()
        showToast('已更新')
        cancelEdit()
      }
      else showToast(r.error || '失败', 'error')
    } catch (e) {
      showToast(e.message || '保存失败', 'error')
    } finally {
      editSubmitting.value = false
    }
  }

  function toggleSelect(id) {
    const idx = selectedIds.value.indexOf(id)
    if (idx >= 0) selectedIds.value.splice(idx, 1)
    else selectedIds.value.push(id)
  }
  function toggleSelectAll() {
    if (allSelected.value) selectedIds.value = []
    else selectedIds.value = items.value.map(it => it.id)
  }
  function openBatchComplete() {
    batchErrors.value = []
    batchReason.value = ''
    batchResult.value = 'ok'
    showBatchModal.value = true
  }
  async function doBatchComplete() {
    if (!selectedIds.value.length) { showToast('请选择返工记录', 'error'); return }
    if (batchSubmitting.value) return
    batchSubmitting.value = true
    batchErrors.value = []
    try {
      const d = await api.domains.rework.batchCompleteRework({
        ids: selectedIds.value,
        reason: batchReason.value,
        result: batchResult.value,
        result_remark: ''
      })
      if (d.ok) {
        batchErrors.value = d.errors || []
        const hasErrors = batchErrors.value.length > 0
        const msg = hasErrors
          ? `已完成 ${d.completed} 条，${batchErrors.value.length} 条失败`
          : `已完成 ${d.completed} 条返工`
        showToast(msg, hasErrors ? 'warn' : 'success')
        selectedIds.value = []
        if (!hasErrors) {
          showBatchModal.value = false
          batchReason.value = ''
        }
        await load(page.value)
        await loadStats()
      }
    } catch (e) {
      showToast(e.message || '操作失败', 'error')
    } finally {
      batchSubmitting.value = false
    }
  }
  function exportData() {
    const qs = []
    if (statusFilter.value) qs.push('status=' + statusFilter.value)
    if (search.value) qs.push('search=' + encodeURIComponent(search.value))
    if (dateFrom.value) qs.push('from=' + dateFrom.value)
    if (dateTo.value) qs.push('to=' + dateTo.value)
    if (filterWorker.value) qs.push('worker_id=' + filterWorker.value)
    if (filterProcess.value) qs.push('process_id=' + filterProcess.value)
    window.open('/api/rework/export?' + qs.join('&'), '_blank')
  }

  async function loadDropdowns() {
    try {
      const w = await api.domains.users.listUsers({limit: 200})
      workers.value = w.users || w.items || []
    } catch (e) { console.warn('Workers dropdown load failed:', e); workers.value = [] }
    try {
      const p = await api.domains.processes.listProcesses({limit: 200})
      processes.value = p.processes || p.items || []
    } catch (e) { console.warn('Processes dropdown load failed:', e); processes.value = [] }
  }

  function switchTab(status) { statusFilter.value = status; search.value = ''; filterWorker.value = ''; filterProcess.value = ''; selectedIds.value = []; page.value = 1; load() }
  function applyFilter() { page.value = 1; selectedIds.value = []; load() }

  onMounted(() => { loadDropdowns(); load(); loadStats() })

  return { items, loading, statusFilter, search, filterWorker, filterProcess, workers, processes, stats, editing, editReason, editSubmitting, dateFrom, dateTo, page, total, perPage, fmtDate, fmtDatetime, isOverdue, overdueHours, load, loadStats, completingItem, completeResult, completeResultRemark, completeSubmitting, openComplete, closeComplete, doComplete, startEdit, cancelEdit, saveEdit, switchTab, applyFilter, canEdit, selectedIds, allSelected, showBatchModal, batchReason, batchResult, batchErrors, batchSubmitting, openBatchComplete, toggleSelect, toggleSelectAll, doBatchComplete, exportData }
}
