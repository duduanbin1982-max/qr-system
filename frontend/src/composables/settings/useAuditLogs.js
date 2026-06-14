// useAuditLogs.js
import { ref, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useAuditLogs() {
  const logs = ref([])
  const logsTotal = ref(0)
  const logsPage = ref(1)
  const logsLoading = ref(false)
  const logsLimit = ref(20)
  const logFilterAction = ref('')
  const logFilterKeyword = ref('')
  const logFilterDateFrom = ref('')
  const logFilterDateTo = ref('')
  const logFilterCategory = ref('')
  const expandedLogId = ref(null)

  async function loadLogs() {
    logsLoading.value = true
    try {
      const params = new URLSearchParams({ page: logsPage.value, limit: logsLimit.value })
      if (logFilterAction.value) params.set('action', logFilterAction.value)
      if (logFilterKeyword.value) params.set('keyword', logFilterKeyword.value)
      if (logFilterDateFrom.value) params.set('date_from', logFilterDateFrom.value)
      if (logFilterDateTo.value) params.set('date_to', logFilterDateTo.value)
      if (logFilterCategory.value) params.set('category', logFilterCategory.value)
      const d = await api.get('/api/logs?' + params.toString())
      logs.value = d.logs || []
      logsTotal.value = d.total || 0
    } catch(e) { showToast(e.message,'error') }
    finally { logsLoading.value = false }
  }

  function doSearch() { logsPage.value = 1; loadLogs() }

  function resetFilters() {
    logFilterAction.value = ''
    logFilterKeyword.value = ''
    logFilterDateFrom.value = ''
    logFilterDateTo.value = ''
    logFilterCategory.value = ''
    doSearch()
  }

  async function clearLogs(beforeDays) {
    const days = beforeDays || 90
    if (!confirm('确定清除 ' + days + ' 天前的日志？')) return
    try {
      const r = await api.post('/api/logs/clear', { before_days: days })
      showToast('已清除 ' + (r.deleted || r.cleared || 0) + ' 条日志')
    } catch(e) { showToast(e.message,'error') }
    loadLogs()
  }

  function logsPrevPage() { if (logsPage.value > 1) { logsPage.value--; loadLogs() } }
  function logsNextPage() { if (logsPage.value * logsLimit.value < logsTotal.value) { logsPage.value++; loadLogs() } }

  onMounted(() => { loadLogs() })

  return {
    logs, logsTotal, logsPage, logsLoading, logsLimit,
    logFilterAction, logFilterKeyword, logFilterDateFrom, logFilterDateTo, logFilterCategory,
    expandedLogId,
    loadLogs, doSearch, resetFilters, clearLogs, logsPrevPage, logsNextPage,
  }
}
