<template>
  <section class="batch-panel">
    <div class="card batch-toolbar-card">
      <div class="card-header batch-toolbar">
        <div><h3>绩效批次审批</h3><p>版本化制单、主管复核、独立批准和版本取代。</p></div>
        <div class="toolbar-actions">
          <select class="form-input batch-select" :value="selectedBatchId || ''" @change="$emit('select', $event.target.value)">
            <option value="">暂无批次</option>
            <option v-for="item in batches" :key="item.id" :value="item.id">{{ item.production_month }} · V{{ item.version }} · {{ statusLabel(item.status) }}</option>
          </select>
          <button class="btn btn-sm" @click="$emit('refresh')">刷新</button>
          <button v-if="canPrepare" class="btn btn-primary btn-sm" :disabled="working" @click="$emit('create')">新建月度草稿</button>
        </div>
      </div>
    </div>

    <div v-if="current" class="batch-detail-grid">
      <div class="batch-overview">
        <div><span>版本</span><strong>V{{ current.version }}</strong></div>
        <div><span>状态</span><strong>{{ statusLabel(current.status) }}</strong></div>
        <div><span>制单人</span><strong>{{ current.prepared_by_name || '-' }}</strong></div>
        <div><span>参评 / 数据不足</span><strong>{{ detail.eligible_count || 0 }} / {{ detail.insufficient_data_count || 0 }}</strong></div>
        <div><span>待处理异常</span><strong>{{ detail.exception_count ?? current.pending_exception_count ?? 0 }}</strong></div>
        <div><span>记录版本</span><strong>{{ current.row_version }}</strong></div>
      </div>
      <div class="batch-actions">
        <button v-if="canAction('submit_supervisor_review') && canPrepare" data-testid="batch-action-submit-review" class="btn btn-primary btn-sm" :disabled="working" @click="$emit('action', 'submit_supervisor_review', current)">提交主管复核</button>
        <button v-if="canAction('submit_approval') && canPrepare" class="btn btn-primary btn-sm" :disabled="working" @click="$emit('action', 'submit_approval', current)">提交批准</button>
        <button v-if="canAction('approve') && canApprove" class="btn btn-success btn-sm" :disabled="working" @click="$emit('action', 'approve', current)">批准并取代旧版</button>
        <button v-if="canAction('return') && (canPrepare || canApprove)" class="btn btn-sm" :disabled="working" @click="$emit('action', 'return', current)">退回</button>
        <button v-if="canAction('cancel') && canPrepare" class="btn btn-danger btn-sm" :disabled="working" @click="$emit('action', 'cancel', current)">取消批次</button>
        <button v-if="canAction('create_revision') && canPrepare" class="btn btn-primary btn-sm" :disabled="working" @click="$emit('action', 'create_revision', current)">创建修订版</button>
      </div>

      <div class="card batch-members-card">
        <div class="card-header"><h3>批次员工评分</h3><span>{{ detail.scores_total || 0 }} 人</span></div>
        <div class="card-body table-wrap">
          <table v-if="detail.scores?.length" class="data-table batch-members-table">
            <thead><tr><th>员工</th><th>部门 / 岗位</th><th>参评状态</th><th>总分</th><th>岗位排名</th><th>预警</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in detail.scores" :key="row.id">
              <td><strong>{{ row.employee_name_snapshot || row.user_name }}</strong><small>{{ row.employee_no_snapshot || row.employee_no || '-' }}</small></td>
              <td>{{ row.department_name_snapshot || row.department_name || '-' }}<small>{{ row.position_name_snapshot || row.position_name || '-' }}</small></td>
              <td>{{ row.eligibility_status === 'eligible' ? '正常参评' : '数据不足' }}</td>
              <td>{{ row.eligibility_status === 'eligible' ? row.total_score : '-' }}</td>
              <td>{{ row.eligibility_status === 'eligible' ? displayRank(row) : '-' }}</td>
              <td>{{ row.eligibility_status === 'eligible' ? warningText(row.warning_level) : '-' }}</td>
              <td class="action-cell"><button class="btn btn-sm" @click="$emit('detail-score', row)">依据</button><button v-if="canReview && row.allowed_actions?.includes('review')" class="btn btn-sm btn-primary" @click="$emit('review', row)">主管复核</button></td>
            </tr></tbody>
          </table>
          <p v-else class="empty">当前批次没有可见员工评分。</p>
        </div>
      </div>

      <div v-if="detail.events?.length" class="card batch-events-card">
        <div class="card-header"><h3>审批轨迹</h3></div>
        <div class="card-body event-list"><div v-for="event in detail.events" :key="event.id"><span>{{ event.created_at }}</span><strong>{{ eventLabel(event.event_type) }}</strong><span>{{ event.operator_name || '-' }}</span><p v-if="event.reason">{{ event.reason }}</p></div></div>
      </div>
    </div>
    <div v-else class="card"><div class="card-body empty">当前生产月暂无可见批次。</div></div>
  </section>
</template>

<script>
export default {
  props: {
    batches: { type: Array, default: () => [] },
    selectedBatchId: { type: [Number, String], default: null },
    detail: { type: Object, default: null },
    canPrepare: { type: Boolean, default: false },
    canApprove: { type: Boolean, default: false },
    canReview: { type: Boolean, default: false },
    working: { type: Boolean, default: false },
    warningText: { type: Function, required: true },
  },
  emits: ['refresh', 'select', 'create', 'action', 'review', 'detail-score'],
  computed: {
    current() { return this.detail?.batch || this.detail || null },
  },
  methods: {
    canAction(action) { return (this.detail?.allowed_actions || this.current?.allowed_actions || []).includes(action) },
    displayRank(row) { return row.rank_no != null && row.rank_total != null ? `${row.rank_no}/${row.rank_total}` : '-' },
    statusLabel(status) { return { draft: '草稿', supervisor_review: '主管复核', approval_pending: '待批准', approved: '已批准', superseded: '已取代', cancelled: '已取消' }[status] || status || '-' },
    eventLabel(type) { return { batch_generated: '生成草稿', batch_submitted_supervisor_review: '提交主管复核', supervisor_review_saved: '保存主管复核', batch_submitted_approval: '提交批准', batch_approved: '批准', batch_returned_draft: '退回草稿', batch_returned_supervisor_review: '退回主管复核', batch_cancelled: '取消', batch_superseded: '版本取代' }[type] || type },
  },
}
</script>

<style scoped>
.batch-panel{min-width:0;max-width:100%;display:grid;gap:var(--space-4)}.batch-toolbar-card{min-width:0;margin:0}.batch-toolbar{align-items:flex-start}.batch-toolbar h3{margin:0}.batch-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.toolbar-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.batch-select{width:min(330px,100%)}
.batch-detail-grid{min-width:0;display:grid;grid-template-columns:minmax(0,2fr) minmax(260px,1fr);gap:var(--space-4)}.batch-overview{grid-column:1/-1;display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:var(--radius-md);overflow:hidden}.batch-overview>div{display:grid;gap:5px;padding:12px;background:var(--bg-card)}.batch-overview span{font-size:var(--text-xs-alt);color:var(--text-placeholder)}.batch-actions{grid-column:1/-1;display:flex;gap:8px;flex-wrap:wrap}.batch-members-card,.batch-events-card{min-width:0;overflow:hidden;margin:0}.batch-members-table{min-width:880px}.batch-members-table strong,.batch-members-table small{display:block}.batch-members-table small{margin-top:3px;color:var(--text-placeholder)}.action-cell{white-space:nowrap}.action-cell .btn+.btn{margin-left:5px}.event-list{display:grid;gap:10px}.event-list>div{display:grid;grid-template-columns:130px 1fr 100px;gap:8px;border-bottom:1px solid var(--border-light);padding-bottom:8px;font-size:var(--text-sm)}.event-list span{color:var(--text-placeholder)}.event-list p{grid-column:2/-1;margin:0;color:var(--text-secondary)}
@media(max-width:1100px){.batch-overview{grid-template-columns:repeat(3,1fr)}.batch-detail-grid{grid-template-columns:1fr}}
@media(max-width:620px){.batch-toolbar{display:grid;gap:12px}.toolbar-actions,.toolbar-actions>*{width:100%}.batch-overview{grid-template-columns:repeat(2,1fr)}.event-list>div{grid-template-columns:1fr}.event-list p{grid-column:auto}}
</style>
