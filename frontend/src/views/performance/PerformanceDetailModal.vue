<template>
  <div class="modal-overlay">
    <div class="modal" style="max-width:680px">
      <div class="modal-header"><span>评分依据 - {{ score.user_name }}</span><span class="modal-close" @click="$emit('close')">&times;</span></div>
      <div class="modal-body" style="display:grid;gap:var(--space-3);font-size:var(--text-sm)">
        <div class="score-grid">
          <div><b>产量分</b><span>{{ score.output_score }}/{{ weight('output') }}</span></div>
          <div><b>质量分</b><span>{{ score.quality_score }}/{{ weight('quality') }}</span></div>
          <div><b>交付分</b><span>{{ score.delivery_score }}/{{ weight('delivery') }}</span></div>
          <div><b>纪律分</b><span>{{ score.discipline_score }}/{{ weight('discipline') }}</span></div>
          <div><b>改进分</b><span>{{ score.improvement_score }}/{{ weight('improvement') }}</span></div>
          <div><b>主管评议</b><span>{{ score.manual_score ?? 10 }}/10</span></div>
        </div>
        <div>岗位：{{ positionName }}，岗位内排名：{{ score.rank_no }}/{{ score.rank_total }}，岗位最高产量：{{ detailValue('position_max_output') || detailValue('max_output') }}</div>
        <div>产量：{{ score.output_qty }}，本次产量分仅与同岗位员工比较。</div>
        <div>质量扣项：报废 {{ score.scrap_qty || 0 }}，返工 {{ score.rework_qty || 0 }}，抽检不合格 {{ score.inspection_failed_qty || 0 }}。</div>
        <div>工序质量评价：共 {{ detailValue('handoff_review_count') }} 次，平均 {{ detailValue('handoff_avg_rating') || '-' }} 分，低分 {{ detailValue('handoff_low_count') }} 次，扣质量分 {{ detailValue('handoff_penalty') }}。</div>
        <div>改进闭环：未关闭 {{ detailValue('open_improvement_plans') }} 项，复评未通过 {{ detailValue('failed_improvement_plans') }} 项，已关闭 {{ detailValue('completed_improvement_plans') }} 项。</div>
        <div>纪律原因：{{ score.discipline_reason || '无' }}</div>
        <div>改进说明：{{ score.improvement_reason || '无' }}</div>
        <div>主管评语：{{ score.manual_comment || '无' }}</div>
        <div>预警原因：{{ score.warning_reason }}</div>
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
  },
  emits: ['close'],
  computed: {
    positionName() {
      return this.score?.position_name || this.score?.score_details?.position_name || '未设置岗位'
    },
  },
  methods: {
    detailValue(key) {
      return this.score?.score_details?.[key] ?? 0
    },
    weight(key) {
      return this.score?.score_details?.weights?.[key] ?? this.rules?.weights?.[key] ?? 0
    },
  },
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
