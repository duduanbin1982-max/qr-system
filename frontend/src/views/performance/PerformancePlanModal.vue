<template>
  <div class="modal-overlay">
    <div class="modal" style="max-width:560px">
      <div class="modal-header"><span>新建改进计划 - {{ score.user_name }}</span><span class="modal-close" @click="$emit('close')">&times;</span></div>
      <div class="modal-body" style="display:grid;gap:var(--space-3)">
        <label>原因<input class="form-input" v-model="form.reason"></label>
        <label>改进目标<textarea class="form-input" v-model="form.goal" rows="3"></textarea></label>
        <label>措施安排<textarea class="form-input" v-model="form.actions" rows="3"></textarea></label>
        <label>截止日期<input type="date" class="form-input" v-model="form.due_date"></label>
      </div>
      <div class="modal-footer"><button class="btn" @click="$emit('close')">取消</button><button class="btn btn-primary" @click="$emit('save')">保存</button></div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    score: { type: Object, required: true },
    form: { type: Object, required: true },
  },
  emits: ['close', 'save'],
}
</script>
