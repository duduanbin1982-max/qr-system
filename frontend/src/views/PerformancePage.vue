<template>
  <div style="padding:var(--space-6)">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <div>
          <h3>🎯 绩效量化管理</h3>
          <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder);margin-top:4px">
            {{ scoringFormula }}；产量分按同岗位员工当月最高产量折算，排名为岗位内排名。
          </div>
        </div>
        <div style="display:flex;gap:var(--space-2);align-items:center;flex-wrap:wrap">
          <input type="month" class="form-input" v-model="yearMonth" style="width:150px">
          <select class="form-input" v-model="warningLevel" style="width:130px">
            <option value="">全部预警</option>
            <option value="green">绿色</option>
            <option value="yellow">黄色</option>
            <option value="orange">橙色</option>
            <option value="red">红色</option>
          </select>
          <select class="form-input" v-model="positionId" style="width:150px" @change="loadScores">
            <option value="">全部岗位</option>
            <option v-for="position in positionOptions" :key="position.id" :value="String(position.id)">
              {{ position.name }}（{{ position.employee_count }}人）
            </option>
          </select>
          <input class="form-input" v-model="search" placeholder="姓名/工号" style="width:160px">
          <button class="btn btn-primary btn-sm" @click="loadScores">查询</button>
          <button v-if="canCreate" class="btn btn-success btn-sm" @click="generateScores">生成/重算本月评分</button>
        </div>
      </div>
    </div>

    <div class="summary-bar" style="margin-bottom:var(--space-4)">
      <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val text-primary">{{ summary.total || 0 }}</div><div class="s-label">{{ positionId ? '当前岗位人数' : '参评人数' }}</div></div></div>
      <div class="summary-item"><span class="s-icon">⭐</span><div><div class="s-val text-success">{{ summary.avg_score || 0 }}</div><div class="s-label">平均分</div></div></div>
      <div class="summary-item"><span class="s-icon">🟢</span><div><div class="s-val">{{ summary.green || 0 }}</div><div class="s-label">绿色</div></div></div>
      <div class="summary-item"><span class="s-icon">🟡</span><div><div class="s-val text-warning">{{ summary.yellow || 0 }}</div><div class="s-label">黄色</div></div></div>
      <div class="summary-item"><span class="s-icon">🟠</span><div><div class="s-val text-warning">{{ summary.orange || 0 }}</div><div class="s-label">橙色</div></div></div>
      <div class="summary-item"><span class="s-icon">🔴</span><div><div class="s-val text-danger">{{ summary.red || 0 }}</div><div class="s-label">红色</div></div></div>
    </div>

    <div v-if="performanceNotice" class="card" style="margin-bottom:var(--space-4);border-left:4px solid var(--warning)">
      <div class="card-body" style="display:flex;justify-content:space-between;gap:var(--space-3);align-items:center;flex-wrap:wrap">
        <div>
          <div style="font-weight:600;color:var(--warning)">{{ performanceNotice.title }}</div>
          <div style="font-size:var(--text-sm);color:var(--text-secondary);margin-top:4px">{{ performanceNotice.message }}</div>
        </div>
        <button v-if="canCreate && performanceNotice.canGenerate" class="btn btn-success btn-sm" @click="generateCurrentMonthScores">生成本月评分</button>
      </div>
    </div>

    <PerformanceScoreTable
      :scores="scores"
      :can-create="canCreate"
      :can-edit="canEdit"
      :warning-text="warningText"
      :warning-class="warningClass"
      :bad-qty="badQty"
      @detail="openDetail"
      @review="openReview"
      @plan="openPlan"
    />

    <HandoffReviewTable
      :reviews="handoffReviews"
      :can-edit="canEdit"
      @confirm="confirmHandoff"
    />

    <ImprovementPlanTable
      :plans="plans"
      :can-edit="canEdit"
      :warning-text="warningText"
      :warning-class="warningClass"
      @close="closePlan"
    />

    <PerformanceDetailModal
      v-if="detailModal"
      :score="selectedScore"
      :rules="rules"
      @close="detailModal=false"
    />

    <PerformanceReviewModal
      v-if="reviewModal"
      :score="selectedScore"
      :form="reviewForm"
      @close="reviewModal=false"
      @save="saveReviewForm"
    />

    <PerformancePlanModal
      v-if="planModal"
      :score="selectedScore"
      :form="planForm"
      @close="planModal=false"
      @save="savePlanForm"
    />
  </div>
</template>

<script>
import { computed, onMounted } from 'vue'
import { can } from '@/lib/auth.js'
import { usePerformancePageData } from '@/composables/usePerformancePageData.js'
import { usePerformanceNotice } from '@/composables/usePerformanceNotice.js'
import { usePerformanceModals } from '@/composables/usePerformanceModals.js'
import PerformanceScoreTable from './performance/PerformanceScoreTable.vue'
import HandoffReviewTable from './performance/HandoffReviewTable.vue'
import ImprovementPlanTable from './performance/ImprovementPlanTable.vue'
import PerformanceDetailModal from './performance/PerformanceDetailModal.vue'
import PerformanceReviewModal from './performance/PerformanceReviewModal.vue'
import PerformancePlanModal from './performance/PerformancePlanModal.vue'

export default {
  components: { PerformanceScoreTable, HandoffReviewTable, ImprovementPlanTable, PerformanceDetailModal, PerformanceReviewModal, PerformancePlanModal },
  setup() {
    const data = usePerformancePageData()
    const modals = usePerformanceModals(data)
    const canCreate = computed(() => can('performance:create'))
    const canEdit = computed(() => can('performance:edit'))
    const scoringFormula = computed(() => {
      const weights = data.rules.value?.weights || {}
      return `评分 = 产量${weights.output ?? 35} + 质量${weights.quality ?? 30} + 交付${weights.delivery ?? 15} + 纪律${weights.discipline ?? 10} + 改进${weights.improvement ?? 10} + 主管评议调整`
    })

    const { performanceNotice, generateCurrentMonthScores } = usePerformanceNotice(data)

    function warningText(level) {
      return { green: '绿色', yellow: '黄色', orange: '橙色', red: '红色' }[level] || level
    }
    function warningClass(level) {
      return { green: 'badge-success', yellow: 'badge-warning', orange: 'badge-warning', red: 'badge-danger' }[level] || 'badge-info'
    }
    function badQty(row) {
      return (row.scrap_qty || 0) + (row.rework_qty || 0) + (row.inspection_failed_qty || 0)
    }
    onMounted(data.initPerformancePage)
    return {
      ...data,
      ...modals,
      canCreate,
      canEdit,
      scoringFormula,
      performanceNotice,
      generateCurrentMonthScores,
      warningText,
      warningClass,
      badQty,
    }
  }
}
</script>
