// ApprovalPage Component — 审批管理
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { can } from '../../auth.js'

export default {
  template: '#approval-page-template',
  setup() {
    const approvals = ref([])
    const loading = ref(true)
    const processing = ref({})
    const activeTab = ref('pending')  // 'pending' | 'history'
    const history = ref([])
    const historyTotal = ref(0)
    const historyPage = ref(1)
    const historyLoading = ref(false)
    const rejectComment = ref({})  // { [id]: comment }

    const canApprove = computed(() => can('approvals:edit'))

    async function load() {
      loading.value = true
      try {
        const d = await api.pendingApprovals()
        approvals.value = d.approvals || []
      } catch(e) { showToast(e.message || '加载失败', 'error') }
      finally { loading.value = false }
    }

    async function loadHistory() {
      historyLoading.value = true
      try {
        const d = await api.approvalHistory({ page: historyPage.value })
        history.value = d.approvals || []
        historyTotal.value = d.total || 0
      } catch(e) { showToast(e.message || '加载失败', 'error') }
      finally { historyLoading.value = false }
    }

    function setTab(tab) {
      activeTab.value = tab
      if (tab === 'history') loadHistory()  // 每次切换都刷新
    }

    async function handle(id, action) {
      if (!canApprove.value) return
      processing.value[id] = true
      try {
        const comment = action === 'reject' ? (rejectComment.value[id] || '') : ''
        await api.handleApproval(id, action, comment)
        showToast(action === 'approve' ? '已批准' : '已拒绝')
        delete rejectComment.value[id]
        await load()
      } catch(e) { showToast(e.message || '操作失败', 'error') }
      finally { processing.value[id] = false }
    }

    onMounted(() => load())

    return {
      approvals, loading, processing, canApprove,
      activeTab, setTab, history, historyTotal, historyPage, historyLoading, loadHistory,
      rejectComment, handle
    }
  }
}
