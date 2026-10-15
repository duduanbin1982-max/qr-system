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
import { usePerformanceWorkspace } from '@/composables/performance/usePerformanceWorkspace.js'

export default {
  components: { PerformanceScoreTable, ImprovementPlanTable, PerformanceDetailModal, PerformanceReviewModal, PerformancePlanModal, PerformancePlanWorkflowModal, PerformanceBatchPanel, PerformanceComparisonPanel, PerformanceExceptionPanel, PerformanceTargetPanel, PerformanceScopePanel },
  setup() {
    return usePerformanceWorkspace()
  },
}
</script>

<style scoped>
.performance-page{box-sizing:border-box;width:100%;max-width:100vw;min-width:0;padding:var(--space-6);display:grid;gap:var(--space-4);overflow:hidden}.performance-page>*{min-width:0}.performance-header-card{margin:0}.performance-header{align-items:flex-start}.performance-header h3{margin:0}.performance-header p{margin:4px 0 0;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.performance-filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.performance-filters .form-input{width:140px}.performance-filters input[placeholder]{width:160px}.result-meta{display:flex;gap:8px;flex-wrap:wrap;padding:10px 16px;border-top:1px solid var(--border-light);color:var(--text-secondary);font-size:var(--text-xs-alt)}.result-meta span{padding:3px 7px;background:var(--bg-secondary);border-radius:4px}.performance-tabs{display:flex;gap:var(--space-1);flex-wrap:wrap;margin:0}.performance-summary{margin:0}.performance-summary .summary-item{min-width:125px}.performance-page :deep(.table-wrap){max-width:100%;overflow-x:auto}
@media(max-width:800px){.performance-page{padding:var(--space-3)}.performance-header{display:grid;gap:12px}.performance-filters,.performance-filters>*{width:100%!important}.performance-tabs{overflow-x:auto;flex-wrap:nowrap;padding-bottom:2px}.performance-tabs .tab-btn{white-space:nowrap;flex:0 0 auto}}
</style>
