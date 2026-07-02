<template>
  <div style="padding:var(--space-6)">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <div>
          <h3>🎯 绩效量化管理</h3>
          <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder);margin-top:4px">
            {{ scoringFormula }}
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
          <input class="form-input" v-model="search" placeholder="姓名/工号" style="width:160px">
          <button class="btn btn-primary btn-sm" @click="loadScores">查询</button>
          <button v-if="canCreate" class="btn btn-success btn-sm" @click="generateScores">生成/重算本月评分</button>
        </div>
      </div>
    </div>

    <div class="summary-bar" style="margin-bottom:var(--space-4)">
      <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val text-primary">{{ summary.total || 0 }}</div><div class="s-label">参评人数</div></div></div>
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

    <div v-if="detailModal" class="modal-overlay">
      <div class="modal" style="max-width:680px">
        <div class="modal-header"><span>评分依据 - {{ selectedScore.user_name }}</span><span class="modal-close" @click="detailModal=false">&times;</span></div>
        <div class="modal-body" style="display:grid;gap:var(--space-3);font-size:var(--text-sm)">
          <div class="score-grid">
            <div><b>产量分</b><span>{{ selectedScore.output_score }}/{{ weight('output') }}</span></div>
            <div><b>质量分</b><span>{{ selectedScore.quality_score }}/{{ weight('quality') }}</span></div>
            <div><b>交付分</b><span>{{ selectedScore.delivery_score }}/{{ weight('delivery') }}</span></div>
            <div><b>纪律分</b><span>{{ selectedScore.discipline_score }}/{{ weight('discipline') }}</span></div>
            <div><b>改进分</b><span>{{ selectedScore.improvement_score }}/{{ weight('improvement') }}</span></div>
            <div><b>主管评议</b><span>{{ selectedScore.manual_score ?? 10 }}/10</span></div>
          </div>
          <div>产量：{{ selectedScore.output_qty }}，当月最高产量：{{ detailValue('max_output') }}</div>
          <div>质量扣项：报废 {{ selectedScore.scrap_qty || 0 }}，返工 {{ selectedScore.rework_qty || 0 }}，抽检不合格 {{ selectedScore.inspection_failed_qty || 0 }}。</div>
          <div>交接评价：共 {{ detailValue('handoff_review_count') }} 次，平均 {{ detailValue('handoff_avg_rating') || '-' }} 分，低分 {{ detailValue('handoff_low_count') }} 次，扣质量分 {{ detailValue('handoff_penalty') }}。</div>
          <div>改进闭环：未关闭 {{ detailValue('open_improvement_plans') }} 项，复评未通过 {{ detailValue('failed_improvement_plans') }} 项，已关闭 {{ detailValue('completed_improvement_plans') }} 项。</div>
          <div>纪律原因：{{ selectedScore.discipline_reason || '无' }}</div>
          <div>改进说明：{{ selectedScore.improvement_reason || '无' }}</div>
          <div>主管评语：{{ selectedScore.manual_comment || '无' }}</div>
          <div>预警原因：{{ selectedScore.warning_reason }}</div>
        </div>
        <div class="modal-footer"><button class="btn" @click="detailModal=false">关闭</button></div>
      </div>
    </div>

    <div v-if="reviewModal" class="modal-overlay">
      <div class="modal" style="max-width:620px">
        <div class="modal-header"><span>主管评议 - {{ selectedScore.user_name }}</span><span class="modal-close" @click="reviewModal=false">&times;</span></div>
        <div class="modal-body" style="display:grid;gap:var(--space-3)">
          <label>纪律扣分（0-10）<input type="number" min="0" max="10" step="0.5" class="form-input" v-model.number="reviewForm.discipline_deduction"></label>
          <label>纪律原因<textarea class="form-input" v-model="reviewForm.discipline_reason" rows="2" placeholder="如迟到、违反现场规范、未按要求扫码等"></textarea></label>
          <label>改进调整（-5 到 5，正数代表改进加分/减扣，负数代表加扣）<input type="number" min="-5" max="5" step="0.5" class="form-input" v-model.number="reviewForm.improvement_adjustment"></label>
          <label>改进说明<textarea class="form-input" v-model="reviewForm.improvement_reason" rows="2" placeholder="如已完成技能提升、复评未通过、改进计划延期等"></textarea></label>
          <label>主管评议分（0-10，低于10会扣入总分）<input type="number" min="0" max="10" step="0.5" class="form-input" v-model.number="reviewForm.manual_score"></label>
          <label>主管评语<textarea class="form-input" v-model="reviewForm.manual_comment" rows="3"></textarea></label>
        </div>
        <div class="modal-footer"><button class="btn" @click="reviewModal=false">取消</button><button class="btn btn-primary" @click="saveReviewForm">保存并重算</button></div>
      </div>
    </div>

    <div v-if="planModal" class="modal-overlay">
      <div class="modal" style="max-width:560px">
        <div class="modal-header"><span>新建改进计划 - {{ selectedScore.user_name }}</span><span class="modal-close" @click="planModal=false">&times;</span></div>
        <div class="modal-body" style="display:grid;gap:var(--space-3)">
          <label>原因<input class="form-input" v-model="planForm.reason"></label>
          <label>改进目标<textarea class="form-input" v-model="planForm.goal" rows="3"></textarea></label>
          <label>措施安排<textarea class="form-input" v-model="planForm.actions" rows="3"></textarea></label>
          <label>截止日期<input type="date" class="form-input" v-model="planForm.due_date"></label>
        </div>
        <div class="modal-footer"><button class="btn" @click="planModal=false">取消</button><button class="btn btn-primary" @click="savePlanForm">保存</button></div>
      </div>
    </div>
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

export default {
  components: { PerformanceScoreTable, HandoffReviewTable, ImprovementPlanTable },
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
    function detailValue(key) {
      return selectedScore.value?.score_details?.[key] ?? 0
    }
    function weight(key) {
      return selectedScore.value?.score_details?.weights?.[key] ?? data.rules.value?.weights?.[key] ?? 0
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
      detailValue,
      weight,
    }
  }
}
</script>

<style scoped>
.score-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--space-2);
}
.score-grid > div {
  border: 1px solid var(--bg-hover);
  border-radius: var(--radius-md);
  padding: var(--space-2);
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
}
.score-grid b { color: var(--text-secondary); }
</style>
