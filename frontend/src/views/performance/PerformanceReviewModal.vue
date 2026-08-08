<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal performance-review-modal">
      <div class="modal-header"><span>主管复核 - {{ score.user_name || score.employee_name_snapshot }}</span><span class="modal-close" @click="$emit('close')">&times;</span></div>
      <div class="modal-body" style="display:grid;gap:var(--space-3)">
        <div class="review-context">批次 V{{ batch.version || '-' }} · {{ batch.production_month || '-' }} · 当前记录版本 {{ batch.row_version || '-' }}</div>
        <label>纪律扣分（0-10）<input type="number" min="0" max="10" step="0.5" class="form-input" v-model.number="form.discipline_deduction"></label>
        <label>纪律原因<textarea class="form-input" v-model="form.discipline_reason" rows="2" placeholder="如迟到、违反现场规范、未按要求扫码等"></textarea></label>
        <label>改进调整（-5 到 5，正数代表改进加分/减扣，负数代表加扣）<input type="number" min="-5" max="5" step="0.5" class="form-input" v-model.number="form.improvement_adjustment"></label>
        <label>改进说明<textarea class="form-input" v-model="form.improvement_reason" rows="2" placeholder="如已完成技能提升、复评未通过、改进计划延期等"></textarea></label>
        <label>主管评议分（0-10，低于10会扣入总分）<input type="number" min="0" max="10" step="0.5" class="form-input" v-model.number="form.manual_score"></label>
        <label>主管评语<textarea class="form-input" v-model="form.manual_comment" rows="3"></textarea></label>
      </div>
      <div class="modal-footer"><button class="btn" @click="$emit('close')">取消</button><button class="btn btn-primary" @click="$emit('save')">保存主管复核</button></div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    score: { type: Object, required: true },
    form: { type: Object, required: true },
    batch: { type: Object, default: () => ({}) },
  },
  emits: ['close', 'save'],
}
</script>

<style scoped>
.performance-review-modal{width:min(620px,94vw);max-height:88vh;display:flex;flex-direction:column}.performance-review-modal .modal-body{overflow:auto}.review-context{padding:9px 10px;background:var(--bg-secondary);color:var(--text-secondary);font-size:var(--text-sm)}
</style>
