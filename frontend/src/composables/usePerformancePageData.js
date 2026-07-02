import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function usePerformancePageData() {
  const yearMonth = ref(new Date().toISOString().slice(0, 7))
  const warningLevel = ref('')
  const search = ref('')
  const scores = ref([])
  const overview = ref({})
  const plans = ref([])
  const handoffReviews = ref([])
  const summary = ref({})
  const rules = ref({})

  async function loadRules() {
    rules.value = await api.performanceRules()
  }

  async function loadOverview() {
    const data = await api.performanceOverview({ year_month: yearMonth.value })
    overview.value = data || {}
    if (data?.display_month && data.display_month !== yearMonth.value) {
      yearMonth.value = data.display_month
    }
  }

  async function loadScores() {
    const data = await api.performanceScores({
      year_month: yearMonth.value,
      warning_level: warningLevel.value,
      search: search.value,
      per_page: 200,
    })
    scores.value = data.items || []
    summary.value = data.summary || {}
    await Promise.all([loadPlans(), loadHandoffReviews()])
  }

  async function loadPlans() {
    const data = await api.performancePlans({ year_month: yearMonth.value })
    plans.value = data.plans || []
  }

  async function loadHandoffReviews() {
    const data = await api.handoffReviews({ year_month: yearMonth.value, per_page: 200 })
    handoffReviews.value = data.items || []
  }

  async function generateScores() {
    const data = await api.generatePerformance({ year_month: yearMonth.value })
    showToast('已生成评分：' + data.generated + ' 人')
    await loadScores()
  }

  async function saveReview(selectedScore, reviewForm) {
    await api.savePerformanceReview({
      user_id: selectedScore.user_id,
      year_month: yearMonth.value,
      ...reviewForm,
    })
    showToast('评议已保存并重算')
    await loadScores()
  }

  async function createPlan(selectedScore, planForm) {
    await api.createPerformancePlan({
      score_id: selectedScore.id,
      user_id: selectedScore.user_id,
      year_month: yearMonth.value,
      warning_level: selectedScore.warning_level,
      ...planForm,
    })
    showToast('改进计划已创建')
    await loadPlans()
  }

  async function closePlan(plan) {
    await api.updatePerformancePlan(plan.id, {
      status: 'closed',
      review_result: 'passed',
      review_notes: '已完成复评',
    })
    showToast('改进计划已关闭')
    await loadPlans()
  }

  async function confirmHandoff(review, status) {
    await api.updateHandoffReviewStatus(review.id, {
      status,
      confirm_note: status === 'confirmed' ? '主管确认' : '主管驳回',
    })
    showToast(status === 'confirmed' ? '交接评价已确认' : '交接评价已驳回')
    await loadScores()
  }

  async function initPerformancePage() {
    await Promise.all([loadRules(), loadOverview()])
    await loadScores()
  }

  return {
    yearMonth,
    warningLevel,
    search,
    scores,
    overview,
    plans,
    handoffReviews,
    summary,
    rules,
    loadScores,
    loadOverview,
    generateScores,
    saveReview,
    createPlan,
    closePlan,
    confirmHandoff,
    initPerformancePage,
  }
}
