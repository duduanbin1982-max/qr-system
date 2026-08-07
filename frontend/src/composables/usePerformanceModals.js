import { ref } from 'vue'

export function usePerformanceModals(data) {
  const planModal = ref(false)
  const reviewModal = ref(false)
  const detailModal = ref(false)
  const selectedScore = ref({})
  const planForm = ref({ reason: '', goal: '', actions: '', owner_id: '', due_date: '' })
  const reviewForm = ref({
    discipline_deduction: 0,
    discipline_reason: '',
    improvement_adjustment: 0,
    improvement_reason: '',
    manual_score: 10,
    manual_comment: '',
  })

  function openDetail(row) {
    selectedScore.value = row
    detailModal.value = true
  }

  function openReview(row) {
    selectedScore.value = row
    reviewForm.value = {
      discipline_deduction: row.discipline_deduction || 0,
      discipline_reason: row.discipline_reason || '',
      improvement_adjustment: row.score_details?.manual_improvement_adjustment || 0,
      improvement_reason: row.improvement_reason || '',
      manual_score: row.manual_score ?? 10,
      manual_comment: row.manual_comment || '',
    }
    reviewModal.value = true
  }

  async function saveReviewForm() {
    await data.saveReview(selectedScore.value, reviewForm.value)
    reviewModal.value = false
  }

  function openPlan(row) {
    selectedScore.value = row
    planForm.value = {
      reason: row.warning_reason || '',
      goal: '明确改进目标并在下期复评',
      actions: '主管面谈、技能辅导、过程跟踪',
      owner_id: '',
      due_date: '',
    }
    planModal.value = true
  }

  async function savePlanForm() {
    await data.createPlan(selectedScore.value, planForm.value)
    planModal.value = false
  }

  return {
    planModal,
    reviewModal,
    detailModal,
    selectedScore,
    planForm,
    reviewForm,
    openDetail,
    openReview,
    saveReviewForm,
    openPlan,
    savePlanForm,
  }
}
