import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function usePerformancePageData() {
  const yearMonth = ref(new Date().toISOString().slice(0, 7))
  const warningLevel = ref('')
  const positionId = ref('')
  const search = ref('')
  const scores = ref([])
  const overview = ref({})
  const plans = ref([])
  const handoffReviews = ref([])
  const summary = ref({})
  const positionOptions = ref([])
  const rules = ref({})

  async function loadRules() {
    rules.value = await api.domains.performance.performanceRules()
  }

  async function loadOverview() {
    const data = await api.domains.performance.performanceOverview({ year_month: yearMonth.value })
    overview.value = data || {}
    if (data?.display_month && data.display_month !== yearMonth.value) {
      yearMonth.value = data.display_month
    }
  }

  async function loadScoreRows() {
    const data = await api.domains.performance.performanceScores({
      year_month: yearMonth.value,
      warning_level: warningLevel.value,
      position_id: positionId.value,
      search: search.value,
      per_page: 200,
    })
    scores.value = data.items || []
    summary.value = data.summary || {}
    positionOptions.value = data.position_options || []
  }

  async function refreshPerformancePageData() {
    await loadScoreRows()
    await Promise.all([loadPlans(), loadHandoffReviews()])
  }

  async function loadScores() {
    await refreshPerformancePageData()
  }

  async function loadPlans() {
    const data = await api.domains.performance.performancePlans({ year_month: yearMonth.value })
    plans.value = data.plans || []
  }

  async function loadHandoffReviews() {
    const data = await api.domains.performance.handoffReviews({ year_month: yearMonth.value, per_page: 200 })
    handoffReviews.value = data.items || []
  }

  async function generateScores() {
    const data = await api.domains.performance.generatePerformance({ year_month: yearMonth.value })
    showToast('已生成评分：' + data.generated + ' 人')
    await refreshPerformancePageData()
  }

  async function saveReview(selectedScore, reviewForm) {
    await api.domains.performance.savePerformanceReview({
      user_id: selectedScore.user_id,
      year_month: yearMonth.value,
      ...reviewForm,
    })
    showToast('评议已保存并重算')
    await refreshPerformancePageData()
  }

  async function createPlan(selectedScore, planForm) {
    await api.domains.performance.createPerformancePlan({
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
    await api.domains.performance.updatePerformancePlan(plan.id, {
      status: 'closed',
      review_result: 'passed',
      review_notes: '已完成复评',
    })
    showToast('改进计划已关闭')
    await loadPlans()
  }

  async function confirmHandoff(review, status) {
    await api.domains.performance.updateHandoffReviewStatus(review.id, {
      status,
      confirm_note: status === 'confirmed' ? '主管确认' : '主管驳回',
    })
    showToast(status === 'confirmed' ? '交接评价已确认' : '交接评价已驳回')
    await refreshPerformancePageData()
  }

  async function initPerformancePage() {
    await Promise.all([loadRules(), loadOverview()])
    await refreshPerformancePageData()
  }

  return {
    yearMonth,
    warningLevel,
    positionId,
    search,
    scores,
    overview,
    plans,
    handoffReviews,
    summary,
    positionOptions,
    rules,
    loadScores,
    loadOverview,
    refreshPerformancePageData,
    generateScores,
    saveReview,
    createPlan,
    closePlan,
    confirmHandoff,
    initPerformancePage,
  }
}
