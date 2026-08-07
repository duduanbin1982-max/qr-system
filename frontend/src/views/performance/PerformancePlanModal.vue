<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal performance-plan-modal">
      <div class="modal-header"><span>新建改进计划 - {{ score.user_name }}</span><span class="modal-close" @click="$emit('close')">&times;</span></div>
      <div class="modal-body" style="display:grid;gap:var(--space-3)">
        <label>问题依据<input class="form-input" v-model="form.reason"></label>
        <label>改进目标<textarea class="form-input" v-model="form.goal" rows="3"></textarea></label>
        <label>措施安排<textarea class="form-input" v-model="form.actions" rows="3"></textarea></label>
        <label>负责人<select class="form-input" v-model="form.owner_id"><option value="">暂不指定</option><option v-for="owner in owners" :key="owner.id" :value="owner.id">{{ owner.name }}{{ owner.employee_no ? `（${owner.employee_no}）` : '' }}</option></select></label>
        <label>截止日期<input type="date" class="form-input" v-model="form.due_date"></label>
      </div>
      <div class="modal-footer"><button class="btn" @click="$emit('close')">取消</button><button class="btn btn-primary" :disabled="!complete" @click="$emit('save')">保存草稿</button></div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    score: { type: Object, required: true },
    form: { type: Object, required: true },
    owners: { type: Array, default: () => [] },
  },
  emits: ['close', 'save'],
  computed: {
    complete() {
      return Boolean(this.form.reason?.trim() && this.form.goal?.trim() && this.form.actions?.trim() && this.form.owner_id && this.form.due_date)
    },
  },
}
</script>

<style scoped>
.performance-plan-modal{width:min(560px,94vw);max-height:88vh;display:flex;flex-direction:column}.performance-plan-modal .modal-body{overflow:auto}.performance-plan-modal label{display:grid;gap:6px;color:var(--text-secondary);font-size:var(--text-sm)}
</style>
