import { computed, onMounted, ref } from 'vue'
import { auth, can } from '@/lib/auth.js'
import { usePerformancePageData } from '@/composables/usePerformancePageData.js'
import { usePerformanceModals } from '@/composables/usePerformanceModals.js'

export function usePerformanceWorkspace() {
  const data = usePerformancePageData()
  const modals = usePerformanceModals(data)
  const activeTab = ref('formal')
  const planWorkflowModal = ref(false)
  const planWorkflowMode = ref('detail')
  const workflowPlan = ref({})

  const canPrepare = computed(() => can('performance:prepare'))
  const canApprove = computed(() => can('performance:approve'))
  const canReview = computed(() => can('performance:review_department'))
  const canPlan = computed(() => can('performance:plan_manage'))
  const canReassess = computed(() => can('performance:plan_reassess'))
  const canViewWorkflow = computed(() => can('performance:view_all') || can('performance:view_department') || can('performance:review_department') || canPrepare.value || canApprove.value)
  const canCompare = computed(() => can('performance:view_all') || canPrepare.value || canApprove.value)
  const canViewPlans = computed(() => can('performance:view_self') || can('performance:view_department') || can('performance:view_all') || canPlan.value || canReassess.value)
  const detailMeta = computed(() => activeTab.value === 'batches' ? (data.batchDetail.value?.batch || data.batchDetail.value || {}) : data.scoreResult.value)
  const headerMeta = computed(() => ['batches', 'comparison', 'exceptions'].includes(activeTab.value) && data.batchDetail.value ? (data.batchDetail.value.batch || data.batchDetail.value) : data.scoreResult.value)
  const sourceLabel = computed(() => headerMeta.value.result_source === 'ledger_v2' || (headerMeta.value.id && !headerMeta.value.legacy_imported) ? 'V2 台账' : 'Legacy 快照')
  const planOwners = computed(() => {
    const current = auth.user ? [{ id: auth.user.id, name: auth.user.name || auth.user.username, employee_no: auth.user.employee_no || '' }] : []
    return [...current, ...data.scopeUsers.value].filter((item, index, items) => items.findIndex(other => Number(other.id) === Number(item.id)) === index)
  })
  const visibleTabs = computed(() => {
    const tabs = [{ key: 'formal', label: '正式结果' }]
    if (canCompare.value) tabs.push({ key: 'comparison', label: '版本对比' })
    if (canViewWorkflow.value) tabs.push({ key: 'batches', label: '批次审批' }, { key: 'exceptions', label: '数据异常' })
    if (canPrepare.value || canApprove.value || can('performance:view_all')) tabs.push({ key: 'targets', label: '岗位目标' })
    if (canViewPlans.value) tabs.push({ key: 'plans', label: '改进计划' })
    if (can('users:admin')) tabs.push({ key: 'scopes', label: '部门授权' })
    return tabs
  })

  async function switchTab(tab) {
    activeTab.value = tab
    if (tab === 'batches' || tab === 'comparison' || tab === 'exceptions') await data.loadBatches()
    if (tab === 'exceptions') await data.loadExceptions()
    if (tab === 'targets') await data.loadConfiguration()
    if (tab === 'plans') await data.loadPlans()
    if (tab === 'scopes') await data.loadScopeSupport()
  }
  async function reloadMonth() {
    await data.loadOverview()
    await data.refreshFormalResults()
    if (activeTab.value !== 'formal') await switchTab(activeTab.value)
  }
  function handleBatchAction(action, batch) {
    if (action === 'submit_supervisor_review') return data.submitSupervisorReview(batch)
    if (action === 'submit_approval') return data.submitApproval(batch)
    if (action === 'approve') return data.approveBatch(batch)
    const reason = window.prompt(action === 'cancel' ? '请输入取消原因' : action === 'create_revision' ? '请输入修订原因' : '请输入退回原因')
    if (!reason?.trim()) return undefined
    if (action === 'return') return data.returnBatch(batch, reason.trim())
    if (action === 'cancel') return data.cancelBatch(batch, reason.trim())
    if (action === 'create_revision') return data.createRevision(batch, reason.trim())
    return undefined
  }
  function openPlanWorkflow(plan, mode) {
    workflowPlan.value = plan
    planWorkflowMode.value = mode
    planWorkflowModal.value = true
    data.loadPlanDetail(plan.id)
  }
  function openPlanDetail(plan) { openPlanWorkflow(plan, 'detail') }
  function openNewPlan(score) { modals.openPlan(score); modals.planForm.value.owner_id = auth.user?.id || '' }
  async function savePlanEvidence(form) { await data.addPlanEvidence(workflowPlan.value, form); planWorkflowModal.value = false }
  async function savePlanReassessment(form) { await data.reassessPlan(workflowPlan.value, form); planWorkflowModal.value = false }
  function activatePlan(plan) { return data.activatePlan(plan) }
  function requestPlanReassessment(plan) { return data.requestPlanReassessment(plan) }

  function warningText(level) { return { green: '绿色', yellow: '黄色', orange: '橙色', red: '红色' }[level] || level || '-' }
  function warningClass(level) { return { green: 'badge-success', yellow: 'badge-warning', orange: 'badge-warning', red: 'badge-danger' }[level] || 'badge-info' }
  function statusLabel(status) { return { approved: '已批准', superseded: '已取代', draft: '草稿', supervisor_review: '主管复核', approval_pending: '待批准', cancelled: '已取消', unavailable: '暂无正式版本' }[status] || status || '暂无正式版本' }
  onMounted(data.initPerformancePage)
  return { ...data, ...modals, activeTab, visibleTabs, canPrepare, canApprove, canReview, canPlan, canReassess, sourceLabel, headerMeta, detailMeta, planOwners, planWorkflowModal, planWorkflowMode, workflowPlan, switchTab, reloadMonth, handleBatchAction, openPlanWorkflow, openPlanDetail, openNewPlan, savePlanEvidence, savePlanReassessment, activatePlan, requestPlanReassessment, warningText, warningClass, statusLabel }
}
