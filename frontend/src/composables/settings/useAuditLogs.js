// useAuditLogs.js
import { ref, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { auth, can } from '@/lib/auth.js'

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
  const logCategories = ref([])
  const expandedLogId = ref(null)
  const cleanupRequests = ref([])
  const canClearLogs = computed(() => can('logs:delete') && can('users:admin'))

  async function loadLogs() {
    logsLoading.value = true
    try {
      const params = new URLSearchParams({ page: logsPage.value, limit: logsLimit.value })
      if (logFilterAction.value) params.set('action', logFilterAction.value)
      if (logFilterKeyword.value) params.set('keyword', logFilterKeyword.value)
      if (logFilterDateFrom.value) params.set('date_from', logFilterDateFrom.value)
      if (logFilterDateTo.value) params.set('date_to', logFilterDateTo.value)
      if (logFilterCategory.value) params.set('category', logFilterCategory.value)
      const d = await api.domains.logs.listLogs(Object.fromEntries(params.entries()))
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
    const days = beforeDays || 1095
    if (!confirm('将提交清理 ' + days + ' 天前日志的申请，审批通过后才会执行。继续？')) return
    const reason = window.prompt('请输入清理理由（至少4个字符）', '')
    if (!reason || reason.trim().length < 4) {
      showToast('清理理由至少需要4个字符', 'error')
      return
    }
    try {
      const r = await api.domains.logs.deleteLogs({ before_days: days, reason: reason.trim() })
      showToast('清理申请已提交，预计影响 ' + (r.affected_count || 0) + ' 条日志')
    } catch(e) { showToast(e.message,'error') }
    loadCleanupRequests()
    loadLogs()
  }

  async function loadCleanupRequests() {
    if (!canClearLogs.value) return
    try {
      const result = await api.domains.logs.listCleanupRequests({ limit: 100 })
      cleanupRequests.value = result.items || []
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  async function loadCategories() {
    try {
      const result = await api.domains.logs.listCategories()
      logCategories.value = result.items || []
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  function canReviewCleanup(item) {
    return item.status === 'pending' && Number(item.requested_by) !== Number(auth.user?.id)
  }

  async function approveCleanup(item) {
    const reason = window.prompt('请输入批准意见（至少4个字符）', '')
    if (!reason || reason.trim().length < 4) return
    if (!confirm('批准后将先归档，再删除符合范围的日志。继续？')) return
    try {
      const result = await api.domains.logs.approveCleanupRequest(item.id, { reason: reason.trim() })
      showToast('已归档 ' + (result.archived || 0) + ' 条并清理 ' + (result.deleted || 0) + ' 条日志')
      await Promise.all([loadCleanupRequests(), loadLogs()])
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  async function rejectCleanup(item) {
    const reason = window.prompt('请输入驳回理由（至少4个字符）', '')
    if (!reason || reason.trim().length < 4) return
    try {
      await api.domains.logs.rejectCleanupRequest(item.id, { reason: reason.trim() })
      showToast('清理申请已驳回')
      await loadCleanupRequests()
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  function cleanupStatusText(status) {
    return ({ pending: '待复核', executed: '已执行', rejected: '已驳回', cancelled: '已取消' })[status] || status
  }

  function logsPrevPage() { if (logsPage.value > 1) { logsPage.value--; loadLogs() } }
  function logsNextPage() { if (logsPage.value * logsLimit.value < logsTotal.value) { logsPage.value++; loadLogs() } }

  onMounted(() => {
    loadLogs()
    loadCategories()
    loadCleanupRequests()
  })

  return {
    logs, logsTotal, logsPage, logsLoading, logsLimit,
    logFilterAction, logFilterKeyword, logFilterDateFrom, logFilterDateTo, logFilterCategory, logCategories,
    expandedLogId, canClearLogs, cleanupRequests,
    loadLogs, doSearch, resetFilters, clearLogs, loadCleanupRequests, loadCategories,
    canReviewCleanup, approveCleanup, rejectCleanup, cleanupStatusText,
    logsPrevPage, logsNextPage,
  }
}
