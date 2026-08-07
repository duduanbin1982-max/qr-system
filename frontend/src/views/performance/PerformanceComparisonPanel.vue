<template>
  <section class="card comparison-panel">
    <div class="card-header comparison-header">
      <div><h3>版本对比</h3><p>仅比较同一生产月的不可变批次版本。</p></div>
      <div class="comparison-controls"><select v-model="baseId" class="form-input"><option value="">基准版本</option><option v-for="item in batches" :key="item.id" :value="item.id">V{{ item.version }} · {{ statusLabel(item.status) }}</option></select><select v-model="compareId" class="form-input"><option value="">对比版本</option><option v-for="item in batches" :key="item.id" :value="item.id">V{{ item.version }} · {{ statusLabel(item.status) }}</option></select><button class="btn btn-primary btn-sm" :disabled="!canCompare" @click="$emit('compare', baseId, compareId)">开始对比</button></div>
    </div>
    <div class="card-body table-wrap">
      <table v-if="comparison?.items?.length" class="data-table comparison-table"><thead><tr><th>员工</th><th>岗位</th><th>差异原因</th><th>变更字段</th><th>前值</th><th>后值</th></tr></thead><tbody><tr v-for="item in changedItems" :key="item.user_id"><td><strong>{{ item.employee_name }}</strong><small>{{ item.employee_no || '-' }}</small></td><td>{{ item.position_name || '-' }}</td><td><span v-for="category in categories(item.changed_fields)" :key="category" class="reason-tag">{{ category }}</span></td><td>{{ fieldLabels(item.changed_fields).join('、') || '无变化' }}</td><td>{{ scoreSummary(item.before) }}</td><td>{{ scoreSummary(item.after) }}</td></tr></tbody></table>
      <p v-else class="empty">选择两个版本后查看参评资格、评分和排名差异。</p>
    </div>
  </section>
</template>

<script>
export default {
  props: { batches: { type: Array, default: () => [] }, comparison: { type: Object, default: null } },
  emits: ['compare'],
  data() { return { baseId: '', compareId: '' } },
  computed: {
    canCompare() { return this.baseId && this.compareId && Number(this.baseId) !== Number(this.compareId) },
    changedItems() { return (this.comparison?.items || []).filter(item => item.changed_fields?.length) },
  },
  watch: {
    batches: { immediate: true, handler(items) { if (!items?.length) return; this.baseId ||= items[0]?.id || ''; this.compareId ||= items[1]?.id || '' } },
  },
  methods: {
    statusLabel(status) { return { draft: '草稿', supervisor_review: '主管复核', approval_pending: '待批准', approved: '已批准', superseded: '已取代', cancelled: '已取消' }[status] || status },
    categories(fields = []) { const result = new Set(); fields.forEach(field => { if (field.startsWith('eligibility_')) result.add('参评资格'); else if (field === 'rank_no' || field === 'rank_total') result.add('岗位排名'); else if (field === 'warning_level') result.add('预警等级'); else if (field.endsWith('_score') || field === 'total_score') result.add('评分结果'); else result.add('来源数据') }); return [...result] },
    fieldLabels(fields = []) { const labels = { eligibility_status: '参评状态', eligibility_reason_code: '资格原因', output_score: '产量分', quality_score: '质量分', delivery_score: '交付分', discipline_score: '纪律分', improvement_score: '改进分', total_score: '总分', warning_level: '预警', rank_no: '排名', rank_total: '参排人数' }; return fields.map(field => labels[field] || field) },
    scoreSummary(value) { if (!value) return '无记录'; if (value.eligibility_status !== 'eligible') return '数据不足'; return `总分 ${value.total_score ?? '-'} · 排名 ${value.rank_no ?? '-'}/${value.rank_total ?? '-'}` },
  },
}
</script>

<style scoped>
.comparison-panel{margin:0}.comparison-header{align-items:flex-start}.comparison-header h3{margin:0}.comparison-header p{margin:4px 0 0;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.comparison-controls{display:flex;gap:8px;flex-wrap:wrap}.comparison-controls select{width:180px}.comparison-table{min-width:980px}.comparison-table strong,.comparison-table small{display:block}.comparison-table small{color:var(--text-placeholder);margin-top:3px}.reason-tag{display:inline-block;margin:2px 4px 2px 0;padding:2px 6px;border-radius:4px;background:var(--primary-light);color:var(--primary);font-size:var(--text-xs-alt)}
@media(max-width:700px){.comparison-header{display:grid;gap:12px}.comparison-controls,.comparison-controls>*{width:100%!important}}
</style>
