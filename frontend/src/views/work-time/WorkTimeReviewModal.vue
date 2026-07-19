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
import { ref, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  record: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])
const reviewForm = ref({})

function hydrate(record) {
  reviewForm.value = record ? {
    id: record.id,
    effective_minutes: record.effective_minutes || record.actual_minutes || 0,
    review_status: record.review_status === 'rejected' ? 'rejected' : 'approved',
    abnormal_reason: record.abnormal_reason || '',
    review_note: record.review_note || '',
  } : {}
}

function close() {
  emit('update:modelValue', false)
}

async function saveReview() {
  try {
    await api.reviewWorkTimeRecord(reviewForm.value.id, { ...reviewForm.value })
    showToast('审核已保存')
    close()
    emit('saved')
  } catch (error) {
    showToast(error.message || '审核失败', 'error')
  }
}

watch(() => props.record, hydrate, { immediate: true })
watch(() => props.modelValue, visible => {
  if (visible) hydrate(props.record)
})
</script>
