import { ref, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useWorkTimeReview(props, emit) {
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
      await api.domains.workTime.reviewWorkTimeRecord(reviewForm.value.id, { ...reviewForm.value })
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

  return {
    reviewForm,
    hydrate,
    close,
    saveReview
  }
}
