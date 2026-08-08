<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal plan-workflow-modal">
      <div class="modal-header"><span>{{ title }}</span><span class="modal-close" @click="$emit('close')">&times;</span></div>
      <div class="modal-body">
        <div class="plan-context">
          <strong>{{ plan.employee_name_snapshot || plan.user_name }}</strong>
          <span>{{ plan.production_month }} · {{ statusLabel(plan.status) }} · 第 {{ plan.reassessment_round || 0 }} 轮</span>
        </div>
        <template v-if="mode === 'detail'">
          <dl class="detail-list"><dt>问题依据</dt><dd>{{ plan.reason || '-' }}</dd><dt>改进目标</dt><dd>{{ plan.goal || '-' }}</dd><dt>行动措施</dt><dd>{{ plan.actions || '-' }}</dd><dt>证据数量</dt><dd>{{ detail.evidence?.length || 0 }}</dd><dt>复评记录</dt><dd>{{ detail.reassessments?.length || 0 }}</dd></dl>
        </template>
        <template v-else-if="mode === 'evidence'">
          <label>证据类型<select v-model="evidenceForm.evidence_type" class="form-input"><option value="note">现场记录</option><option value="training">培训记录</option><option value="quality_record">质量记录</option><option value="attachment">附件</option></select></label>
          <label>证据说明<textarea v-model="evidenceForm.description" class="form-input" rows="4"></textarea></label>
          <label>来源链接<input v-model="evidenceForm.source_url" class="form-input" placeholder="可选"></label>
        </template>
        <template v-else-if="mode === 'reassess'">
          <label>复评结论<select v-model="reassessmentForm.result" class="form-input"><option value="passed">通过并关闭</option><option value="failed">不通过，返回执行</option></select></label>
          <fieldset class="evidence-options"><legend>引用本轮证据</legend><label v-for="item in currentEvidence" :key="item.id"><input v-model="reassessmentForm.evidence_ids" type="checkbox" :value="item.id">{{ item.description || item.file_name || `证据 #${item.id}` }}</label><span v-if="!currentEvidence.length">当前轮次没有可引用证据</span></fieldset>
          <label>复评说明<textarea v-model="reassessmentForm.notes" class="form-input" rows="4"></textarea></label>
          <template v-if="reassessmentForm.result === 'failed'">
            <label>新措施<textarea v-model="reassessmentForm.new_actions" class="form-input" rows="3"></textarea></label>
            <label>新截止日期<input v-model="reassessmentForm.new_due_date" type="date" class="form-input"></label>
          </template>
        </template>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="$emit('close')">{{ mode === 'detail' ? '关闭' : '取消' }}</button>
        <button v-if="mode === 'evidence'" class="btn btn-primary" @click="submitEvidence">提交证据</button>
        <button v-if="mode === 'reassess'" class="btn btn-primary" :disabled="!currentEvidence.length" @click="submitReassessment">提交复评</button>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    mode: { type: String, required: true },
    plan: { type: Object, required: true },
    detail: { type: Object, default: () => ({}) },
  },
  emits: ['close', 'evidence', 'reassess'],
  data() {
    return {
      evidenceForm: { evidence_type: 'note', description: '', source_url: '' },
      reassessmentForm: { result: 'passed', notes: '', evidence_ids: [], new_actions: '', new_due_date: '' },
    }
  },
  computed: {
    title() {
      return { detail: '改进计划详情', evidence: '追加改进证据', reassess: '独立复评' }[this.mode] || '改进计划'
    },
    currentEvidence() {
      const round = Number(this.plan.reassessment_round || 0)
      return (this.detail.evidence || []).filter(item => Number(item.reassessment_round || 0) === round)
    },
  },
  methods: {
    statusLabel(status) {
      return { draft: '草稿', active: '执行中', reassessment_pending: '待复评', closed: '复评通过', cancelled: '已取消' }[status] || status
    },
    submitEvidence() {
      if (!this.evidenceForm.description.trim() && !this.evidenceForm.source_url.trim()) return
      this.$emit('evidence', { ...this.evidenceForm })
    },
    submitReassessment() {
      if (!this.reassessmentForm.notes.trim() || !this.reassessmentForm.evidence_ids.length) return
      this.$emit('reassess', { ...this.reassessmentForm })
    },
  },
}
</script>

<style scoped>
.plan-workflow-modal{width:min(640px,94vw);max-height:88vh;display:flex;flex-direction:column}.plan-workflow-modal .modal-body{display:grid;gap:var(--space-3);overflow:auto}.plan-workflow-modal label{display:grid;gap:6px;color:var(--text-secondary);font-size:var(--text-sm)}
.plan-context{display:flex;justify-content:space-between;gap:12px;padding:10px;background:var(--bg-secondary);font-size:var(--text-sm)}.plan-context span{color:var(--text-placeholder)}
.detail-list{display:grid;grid-template-columns:100px 1fr;gap:10px;margin:0}.detail-list dt{color:var(--text-placeholder)}.detail-list dd{margin:0}.evidence-options{display:grid;gap:8px;border:1px solid var(--border);padding:10px}.evidence-options label{display:flex;align-items:center;gap:8px}
@media(max-width:520px){.plan-context{flex-direction:column}.detail-list{grid-template-columns:1fr}.detail-list dd{padding-bottom:8px}}
</style>
