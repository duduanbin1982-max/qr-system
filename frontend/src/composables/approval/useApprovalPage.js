import { ref, onMounted, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export function useApprovalPage() {
  const approvals = ref([])
  const approvalTotal = ref(0)
  const approvalPage = ref(1)
  const approvalLimit = 20
  const loading = ref(true)
  const filterOrderNo = ref('')
  const filterWorker = ref('')
  const filterProcess = ref('')
  const selectedIds = ref([])
  const selectAll = ref(false)
  const processing = ref({})
  const activeTab = ref('pending')
  const stats = ref({ pending: 0, avg_hours: 0, pending_over_24h: 0, total: 0 })
  const history = ref([])
  const historyTotal = ref(0)
  const historyPage = ref(1)
  const historyLoading = ref(false)
  const rejectComment = ref({})

  const canApprove = computed(() => can('approvals:decision'))
  const filteredApprovals = computed(() => {
    let arr = approvals.value
    if (filterOrderNo.value) {
      const q = filterOrderNo.value.toLowerCase()
      arr = arr.filter(a => (a.order_no || '').toLowerCase().includes(q))
    }
    if (filterWorker.value) {
      const q = filterWorker.value.toLowerCase()
      arr = arr.filter(a => (a.worker_name || '').toLowerCase().includes(q))
    }
    if (filterProcess.value) {
      const q = filterProcess.value.toLowerCase()
      arr = arr.filter(a => (a.process_name || '').toLowerCase().includes(q))
    }
    return arr
  })

  async function load(page = approvalPage.value) {
    loading.value = true
    selectedIds.value = []
    selectAll.value = false
    try {
      const d = await api.domains.approvals.pendingApprovals({ page, limit: approvalLimit })
      approvalPage.value = d.page || page
      approvals.value = d.approvals || []
      approvalTotal.value = d.total || 0
    } catch (e) { showToast(e.message || '加载失败', 'error') }
    finally { loading.value = false }
  }

  function changeApprovalPage(offset) {
    const nextPage = approvalPage.value + offset
    const maxPage = Math.max(1, Math.ceil(approvalTotal.value / approvalLimit))
    if (nextPage < 1 || nextPage > maxPage) return
    load(nextPage)
  }

  async function loadHistory() {
    historyLoading.value = true
    try {
      const d = await api.domains.approvals.approvalHistory({ page: historyPage.value })
      history.value = d.approvals || []
      historyTotal.value = d.total || 0
    } catch (e) { showToast(e.message || '加载失败', 'error') }
    finally { historyLoading.value = false }
  }

  function toggleSelectAll() {
    selectedIds.value = selectAll.value ? filteredApprovals.value.map(a => a.id) : []
  }

  watch([filterOrderNo, filterWorker, filterProcess], () => {
    selectedIds.value = []
    selectAll.value = false
  })

  async function batchHandle(action) {
    if (selectedIds.value.length === 0) return
    const label = action === 'approve' ? '通过' : '拒绝'
    if (!confirm('确定批量' + label + ' ' + selectedIds.value.length + ' 条审批？')) return
    try {
      const result = await api.domains.approvals.batchApproval(selectedIds.value, action)
      if (result.failed && result.failed.length > 0) {
        showToast(result.message + '，' + result.failed.length + ' 条失败', 'warning')
      } else {
        showToast('已批量' + label)
      }
      selectedIds.value = []
      selectAll.value = false
      await Promise.all([load(), loadStats()])
    } catch (e) { showToast(e.message || '操作失败', 'error') }
  }

  function setTab(tab) {
    activeTab.value = tab
    if (tab === 'history') loadHistory()
  }

  async function loadStats() {
    try {
      const d = await api.domains.approvals.approvalStats()
      stats.value = d
    } catch (e) { console.warn('Approval stats load failed:', e) }
  }

  async function handle(id, action) {
    if (!canApprove.value) return
    processing.value[id] = true
    try {
      const comment = action === 'reject' ? (rejectComment.value[id] || '') : ''
      await api.domains.approvals.handleApproval(id, action, comment)
      showToast(action === 'approve' ? '已批准' : '已拒绝')
      delete rejectComment.value[id]
      await Promise.all([load(), loadStats()])
    } catch (e) { showToast(e.message || '操作失败', 'error') }
    finally { processing.value[id] = false }
  }

  onMounted(() => { load(); loadStats() })

  return {
    approvals, approvalTotal, approvalPage, approvalLimit, loading, processing, canApprove, filteredApprovals,
    filterOrderNo, filterWorker, filterProcess,
    activeTab, setTab, history, historyTotal, historyPage, historyLoading, loadHistory,
    rejectComment, handle, selectedIds, selectAll, toggleSelectAll, batchHandle,
    stats, changeApprovalPage
  }
}
