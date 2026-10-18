<template>
  <div v-if="modelValue" class="modal-overlay" @click.self="close">
    <div class="modal" style="max-width:520px">
      <div class="modal-header"><h3>工时审核</h3></div>
      <div class="modal-body">
        <div class="form-group"><label>有效工时（分钟）</label><input class="form-input" type="number" min="0" step="0.1" v-model.number="reviewForm.effective_minutes"></div>
        <div class="form-group"><label>审核结果</label><select class="form-input" v-model="reviewForm.review_status"><option value="approved">通过</option><option value="pending">保留待审</option><option value="rejected">驳回</option></select></div>
        <div class="form-group"><label>异常原因</label><textarea class="form-input" rows="2" v-model="reviewForm.abnormal_reason"></textarea></div>
        <div class="form-group"><label>审核说明</label><textarea class="form-input" rows="2" v-model="reviewForm.review_note"></textarea></div>
      </div>
      <div class="modal-footer"><button class="btn btn-default" @click="close">取消</button><button class="btn btn-primary" @click="saveReview">保存审核</button></div>
    </div>
  </div>
</template>

<script setup>
import { useWorkTimeReview } from '@/composables/workTime/useWorkTimeReview.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  record: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const {
  reviewForm,
  hydrate,
  close,
  saveReview
} = useWorkTimeReview(props, emit)
</script>
