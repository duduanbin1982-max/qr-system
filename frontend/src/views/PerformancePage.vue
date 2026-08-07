<template>
  <div class="performance-page">
    <div class="card performance-header-card">
      <div class="card-header performance-header">
        <div><h3>绩效管理</h3><p>正式结果、批次审批和改进闭环</p></div>
        <div class="performance-filters">
          <input type="month" class="form-input" v-model="yearMonth" @change="reloadMonth">
          <select class="form-input" v-model="warningLevel" @change="loadScores"><option value="">全部预警</option><option value="green">绿色</option><option value="yellow">黄色</option><option value="orange">橙色</option><option value="red">红色</option></select>
          <select class="form-input" v-model="positionId" @change="loadScores"><option value="">全部岗位</option><option v-for="position in positionOptions" :key="position.id" :value="position.id">{{ position.name }}（{{ position.employee_count }}人）</option></select>
          <input class="form-input" v-model="search" placeholder="姓名/工号" @keyup.enter="loadScores"><button class="btn btn-primary btn-sm" @click="loadScores">查询</button>
        </div>
      </div>
      <div class="result-meta"><span data-testid="result-source">来源：{{ sourceLabel }}</span><span data-testid="result-version">版本：V{{ headerMeta.version || '-' }}</span><span data-testid="result-status">批次：{{ statusLabel(headerMeta.batch_status || headerMeta.status) }}</span><span data-testid="production-period">生产日：{{ headerMeta.period_start || '-' }} 至 {{ headerMeta.period_end || '-' }}</span></div>
    </div>

    <nav class="performance-tabs" aria-label="绩效视图">
      <button v-for="tab in visibleTabs" :key="tab.key" :data-testid="`tab-${tab.key}`" class="tab-btn" :class="{active: activeTab===tab.key}" @click="switchTab(tab.key)">{{ tab.label }}</button>
    </nav>

    <template v-if="activeTab === 'formal'">
      <div class="summary-bar performance-summary">
        <div class="summary-item"><div><div class="s-val text-primary">{{ summary.total || 0 }}</div><div class="s-label">可见结果</div></div></div>
        <div class="summary-item"><div><div class="s-val text-success">{{ summary.avg_score ?? '-' }}</div><div class="s-label">合格平均分</div></div></div>
        <div class="summary-item"><div><div data-testid="eligible-count" class="s-val">{{ summary.eligible_count || 0 }}</div><div class="s-label">正常参评</div></div></div>
        <div class="summary-item"><div><div data-testid="insufficient-count" class="s-val text-warning">{{ summary.insufficient_data_count || 0 }}</div><div class="s-label">数据不足</div></div></div>
        <div class="summary-item"><div><div class="s-val">{{ summary.green || 0 }}</div><div class="s-label">绿色</div></div></div>
        <div class="summary-item"><div><div class="s-val text-danger">{{ (summary.yellow || 0) + (summary.orange || 0) + (summary.red || 0) }}</div><div class="s-label">需关注</div></div></div>
      </div>
      <PerformanceScoreTable :scores="scores" :can-plan="canPlan" :warning-text="warningText" :warning-class="warningClass" @detail="openDetail" @plan="openNewPlan" />
      <ImprovementPlanTable :plans="plans" :can-manage="canPlan" :can-reassess="canReassess" :warning-text="warningText" :warning-class="warningClass" @detail="openPlanDetail" @activate="activatePlan" @evidence="openPlanWorkflow($event, 'evidence')" @request-reassessment="requestPlanReassessment" @reassess="openPlanWorkflow($event, 'reassess')" />
    </template>

    <PerformanceBatchPanel v-else-if="activeTab === 'batches'" :batches="batches" :selected-batch-id="selectedBatchId" :detail="batchDetail" :can-prepare="canPrepare" :can-approve="canApprove" :can-review="canReview" :working="working" :warning-text="warningText" @refresh="loadBatches" @select="loadBatchDetail" @create="createBatch" @action="handleBatchAction" @review="openReview" @detail-score="openDetail" />
    <PerformanceComparisonPanel v-else-if="activeTab === 'comparison'" :batches="batches" :comparison="comparison" @compare="loadComparison" />
    <PerformanceExceptionPanel v-else-if="activeTab === 'exceptions'" :items="exceptions" :total="exceptionTotal" />
    <PerformanceTargetPanel v-else-if="activeTab === 'targets'" :targets="targets" :positions="positions" :rule-versions="ruleVersions" :can-prepare="canPrepare" :can-approve="canApprove" :month="yearMonth" @create="createTarget" @approve="approveTarget" />
    <ImprovementPlanTable v-else-if="activeTab === 'plans'" :plans="plans" :can-manage="canPlan" :can-reassess="canReassess" :warning-text="warningText" :warning-class="warningClass" @detail="openPlanDetail" @activate="activatePlan" @evidence="openPlanWorkflow($event, 'evidence')" @request-reassessment="requestPlanReassessment" @reassess="openPlanWorkflow($event, 'reassess')" />
    <PerformanceScopePanel v-else-if="activeTab === 'scopes'" :users="scopeUsers" :departments="scopeDepartments" :selected-user-id="selectedScopeUserId" :department-ids="selectedDepartmentIds" @select-user="loadDepartmentScope" @save="saveDepartmentScope" />

    <PerformanceDetailModal v-if="detailModal" :score="selectedScore" :rules="rules" :meta="detailMeta" @close="detailModal=false" />
    <PerformanceReviewModal v-if="reviewModal" :score="selectedScore" :form="reviewForm" :batch="batchDetail?.batch || batchDetail || {}" @close="reviewModal=false" @save="saveReviewForm" />
    <PerformancePlanModal v-if="planModal" :score="selectedScore" :form="planForm" :owners="planOwners" @close="planModal=false" @save="savePlanForm" />
    <PerformancePlanWorkflowModal v-if="planWorkflowModal" :mode="planWorkflowMode" :plan="workflowPlan" :detail="planDetail || {}" @close="planWorkflowModal=false" @evidence="savePlanEvidence" @reassess="savePlanReassessment" />
  </div>
</template>

<script>
import { computed, onMounted, ref } from 'vue'
import { auth, can } from '@/lib/auth.js'
import { usePerformancePageData } from '@/composables/usePerformancePageData.js'
import { usePerformanceModals } from '@/composables/usePerformanceModals.js'
import PerformanceScoreTable from './performance/PerformanceScoreTable.vue'
import ImprovementPlanTable from './performance/ImprovementPlanTable.vue'
import PerformanceDetailModal from './performance/PerformanceDetailModal.vue'
import PerformanceReviewModal from './performance/PerformanceReviewModal.vue'
import PerformancePlanModal from './performance/PerformancePlanModal.vue'
import PerformancePlanWorkflowModal from './performance/PerformancePlanWorkflowModal.vue'
import PerformanceBatchPanel from './performance/PerformanceBatchPanel.vue'
import PerformanceComparisonPanel from './performance/PerformanceComparisonPanel.vue'
import PerformanceExceptionPanel from './performance/PerformanceExceptionPanel.vue'
import PerformanceTargetPanel from './performance/PerformanceTargetPanel.vue'
import PerformanceScopePanel from './performance/PerformanceScopePanel.vue'

export default {
  components: { PerformanceScoreTable, ImprovementPlanTable, PerformanceDetailModal, PerformanceReviewModal, PerformancePlanModal, PerformancePlanWorkflowModal, PerformanceBatchPanel, PerformanceComparisonPanel, PerformanceExceptionPanel, PerformanceTargetPanel, PerformanceScopePanel },
  setup() {
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
  },
}
</script>

<style scoped>
.performance-page{box-sizing:border-box;width:100%;max-width:100vw;min-width:0;padding:var(--space-6);display:grid;gap:var(--space-4);overflow:hidden}.performance-page>*{min-width:0}.performance-header-card{margin:0}.performance-header{align-items:flex-start}.performance-header h3{margin:0}.performance-header p{margin:4px 0 0;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.performance-filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.performance-filters .form-input{width:140px}.performance-filters input[placeholder]{width:160px}.result-meta{display:flex;gap:8px;flex-wrap:wrap;padding:10px 16px;border-top:1px solid var(--border-light);color:var(--text-secondary);font-size:var(--text-xs-alt)}.result-meta span{padding:3px 7px;background:var(--bg-secondary);border-radius:4px}.performance-tabs{display:flex;gap:var(--space-1);flex-wrap:wrap;margin:0}.performance-summary{margin:0}.performance-summary .summary-item{min-width:125px}.performance-page :deep(.table-wrap){max-width:100%;overflow-x:auto}
@media(max-width:800px){.performance-page{padding:var(--space-3)}.performance-header{display:grid;gap:12px}.performance-filters,.performance-filters>*{width:100%!important}.performance-tabs{overflow-x:auto;flex-wrap:nowrap;padding-bottom:2px}.performance-tabs .tab-btn{white-space:nowrap;flex:0 0 auto}}
</style>
