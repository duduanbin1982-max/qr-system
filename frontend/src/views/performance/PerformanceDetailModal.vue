<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal performance-detail-modal">
      <div class="modal-header"><span>评分依据 - {{ scoreName }}</span><span class="modal-close" @click="$emit('close')">&times;</span></div>
      <div class="modal-body detail-body">
        <div class="detail-meta">
          <span>{{ sourceLabel }}</span><span>V{{ meta.version || '-' }}</span><span>{{ statusLabel(meta.batch_status) }}</span>
        </div>
        <div v-if="!isEligible" class="insufficient-notice">
          <strong>数据不足，本版不生成评分、等级和岗位排名</strong>
          <span>{{ score.eligibility_reason || score.eligibility_reason_code || '来源数据未达到评分条件' }}</span>
        </div>
        <template v-else>
          <div class="score-grid">
            <div><b>产量分</b><span>{{ score.output_score }}/{{ weight('output') }}</span></div>
            <div><b>质量分</b><span>{{ score.quality_score }}/{{ weight('quality') }}</span></div>
            <div><b>交付分</b><span>{{ score.delivery_score }}/{{ weight('delivery') }}</span></div>
            <div><b>纪律分</b><span>{{ score.discipline_score }}/{{ weight('discipline') }}</span></div>
            <div><b>改进分</b><span>{{ score.improvement_score }}/{{ weight('improvement') }}</span></div>
            <div><b>主管评议</b><span>{{ score.manual_score ?? 10 }}/10</span></div>
          </div>
          <div>岗位：{{ score.position_name || score.position_name_snapshot || '未设置岗位' }}；岗位排名：{{ score.rank_no }}/{{ score.rank_total }}。</div>
          <div>岗位目标产量：{{ targetOutput }}；实际产量：{{ score.output_qty ?? 0 }}；有效报工：{{ score.report_count ?? 0 }} 次。</div>
          <div>质量扣项：报废 {{ score.scrap_qty || 0 }}，返工 {{ score.rework_qty || 0 }}，抽检不合格 {{ score.inspection_failed_qty || 0 }}。</div>
          <div>工序质量评价：{{ detailValue('handoff_review_count') }} 次；平均 {{ detailValue('handoff_avg_rating') || '-' }} 分；低分 {{ detailValue('handoff_low_count') }} 次。</div>
          <div>纪律原因：{{ score.discipline_reason || '无' }}</div>
          <div>改进说明：{{ score.improvement_reason || '无' }}</div>
          <div>主管评语：{{ score.manual_comment || '无' }}</div>
          <div>预警原因：{{ score.warning_reason || '无' }}</div>
        </template>
      </div>
      <div class="modal-footer"><button class="btn" @click="$emit('close')">关闭</button></div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    score: { type: Object, required: true },
    rules: { type: Object, default: () => ({}) },
    meta: { type: Object, default: () => ({}) },
  },
  emits: ['close'],
  computed: {
    scoreName() {
      return this.score.user_name || this.score.employee_name_snapshot || '-'
    },
    isEligible() {
      return this.score.eligible === true || this.score.eligibility_status === 'eligible'
    },
    sourceLabel() {
      return this.meta.result_source === 'ledger_v2' ? 'V2 台账' : 'Legacy 快照'
    },
    targetOutput() {
      return this.detailValue('position_target_output')
        || this.detailValue('target_output_qty')
        || this.score.position_target_output
        || '-'
    },
  },
  methods: {
    detailValue(key) {
      return this.score?.score_details?.[key] ?? 0
    },
    weight(key) {
      return this.score?.score_details?.weights?.[key] ?? this.rules?.weights?.[key] ?? 0
    },
    statusLabel(status) {
      return { approved: '已批准', superseded: '已取代', draft: '草稿', supervisor_review: '主管复核', approval_pending: '待批准' }[status] || status || '不可用'
    },
  },
}
</script>

<style scoped>
.performance-detail-modal{width:min(700px,94vw);max-height:88vh;display:flex;flex-direction:column}.detail-body{display:grid;gap:var(--space-3);font-size:var(--text-sm);overflow:auto}
.detail-meta{display:flex;gap:8px;flex-wrap:wrap}.detail-meta span{padding:3px 7px;border-radius:4px;background:var(--bg-secondary);color:var(--text-secondary)}
.insufficient-notice{display:grid;gap:6px;padding:12px;border-left:3px solid var(--warning);background:var(--warning-light)}
.score-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--space-2)}
.score-grid>div{border:1px solid var(--border-light);border-radius:var(--radius-md);padding:var(--space-2);display:flex;justify-content:space-between;gap:var(--space-2)}.score-grid b{color:var(--text-secondary)}
</style>
