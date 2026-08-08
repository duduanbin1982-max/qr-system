<template>
  <section class="target-panel">
    <div class="card target-form-card">
      <div class="card-header"><div><h3>岗位目标版本</h3><p>批准后的目标按生效区间只读，评分批次保存目标版本快照。</p></div><button v-if="canPrepare" class="btn btn-primary btn-sm" @click="showForm=!showForm">{{ showForm ? '收起' : '新建目标草稿' }}</button></div>
      <form v-if="showForm && canPrepare" class="target-form" @submit.prevent="submit">
        <label>岗位<select v-model="form.position_id" class="form-input" required><option value="">请选择</option><option v-for="position in positions" :key="position.id" :value="position.id">{{ position.name }}</option></select></label>
        <label>月目标产量<input v-model.number="form.target_output_qty" type="number" min="0.01" step="0.01" class="form-input" required></label>
        <label>最低有效工作日<input v-model.number="form.minimum_effective_work_days" type="number" min="0" step="0.5" class="form-input" required></label>
        <label>生效月份<input v-model="form.effective_from_month" type="month" class="form-input" required></label>
        <label>失效月份<input v-model="form.effective_to_month" type="month" class="form-input" required></label>
        <button class="btn btn-primary btn-sm" type="submit">保存草稿</button>
      </form>
    </div>

    <div class="card target-list-card"><div class="card-body table-wrap"><table v-if="targets.length" class="data-table target-table"><thead><tr><th>岗位</th><th>目标产量</th><th>最低工作日</th><th>生效区间</th><th>状态</th><th>版本</th><th>创建 / 批准</th><th>操作</th></tr></thead><tbody><tr v-for="item in targets" :key="item.id"><td><strong>{{ item.position_name_snapshot }}</strong><small>岗位 #{{ item.position_id }}</small></td><td>{{ item.target_output_qty }}</td><td>{{ item.minimum_effective_work_days }}</td><td>{{ item.effective_from_month }} 至 {{ item.effective_to_month || '长期' }}</td><td><span class="target-status" :class="`status-${item.status}`">{{ item.status === 'approved' ? '已批准，只读' : '草稿' }}</span></td><td>V{{ item.id }} / R{{ item.row_version }}</td><td>{{ item.created_by_name || '-' }}<small v-if="item.approved_at">{{ item.approved_by_name || '-' }} · {{ item.approved_at }}</small></td><td><button v-if="canApprove && item.status === 'draft'" class="btn btn-success btn-sm" @click="$emit('approve', item)">批准生效</button><span v-else class="readonly-label">{{ item.status === 'approved' ? '已锁定' : '-' }}</span></td></tr></tbody></table><p v-else class="empty">暂无岗位目标版本。</p></div></div>

    <div class="card rule-list-card"><div class="card-header"><h3>评分规则版本</h3></div><div class="card-body table-wrap"><table v-if="ruleVersions.length" class="data-table rule-table"><thead><tr><th>编码</th><th>名称</th><th>生效区间</th><th>状态</th><th>发布人</th></tr></thead><tbody><tr v-for="rule in ruleVersions" :key="rule.id"><td><code>{{ rule.version_code }}</code></td><td>{{ rule.name }}</td><td>{{ rule.effective_from_month }} 至 {{ rule.effective_to_month || '长期' }}</td><td>{{ rule.status === 'published' ? '已发布，只读' : '草稿' }}</td><td>{{ rule.published_by_name || rule.created_by_name || '-' }}</td></tr></tbody></table><p v-else class="empty">暂无可见评分规则版本。</p></div></div>
  </section>
</template>

<script>
export default {
  props: {
    targets: { type: Array, default: () => [] }, positions: { type: Array, default: () => [] }, ruleVersions: { type: Array, default: () => [] }, canPrepare: { type: Boolean, default: false }, canApprove: { type: Boolean, default: false }, month: { type: String, default: '' },
  },
  emits: ['create', 'approve'],
  data() { return { showForm: false, form: { position_id: '', target_output_qty: '', minimum_effective_work_days: 1, effective_from_month: this.month, effective_to_month: '' } } },
  methods: {
    submit() { this.$emit('create', { ...this.form, position_id: Number(this.form.position_id) }); this.showForm = false },
  },
}
</script>

<style scoped>
.target-panel{display:grid;gap:var(--space-4)}.target-panel>.card{margin:0}.target-form-card h3{margin:0}.target-form-card p{margin:4px 0 0;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.target-form{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;padding:12px 16px;border-top:1px solid var(--border-light);background:var(--bg-secondary)}.target-form label{display:grid;gap:5px;min-width:150px;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.target-table{min-width:1050px}.target-table strong,.target-table small{display:block}.target-table small{margin-top:3px;color:var(--text-placeholder)}.target-status{display:inline-block;padding:3px 7px;border-radius:4px;background:var(--bg-secondary)}.status-approved{color:var(--success);background:var(--success-light)}.readonly-label{color:var(--text-placeholder)}.rule-table{min-width:760px}
@media(max-width:620px){.target-form label,.target-form .btn{width:100%;min-width:0}}
</style>
