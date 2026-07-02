import { computed } from 'vue'

export function usePerformanceNotice(data) {
  const performanceNotice = computed(() => {
    const info = data.overview.value || {}
    if (!info.current_month || info.current_month_score_count) return null

    const workRecordCount = info.current_month_work_record_count || 0
    if (!workRecordCount) return null

    if (data.yearMonth.value !== info.current_month) {
      return {
        title: `${info.current_month} 尚未生成绩效评分`,
        message: `系统已自动显示最近有评分数据的 ${data.yearMonth.value}。本月已有 ${workRecordCount} 条已审批报工，可生成本月评分后查看。`,
        canGenerate: true,
      }
    }

    if (!data.scores.value.length) {
      return {
        title: `${info.current_month} 尚未生成绩效评分`,
        message: `本月已有 ${workRecordCount} 条已审批报工，请先生成本月评分。`,
        canGenerate: true,
      }
    }

    return null
  })

  async function generateCurrentMonthScores() {
    if (data.overview.value?.current_month) {
      data.yearMonth.value = data.overview.value.current_month
    }
    await data.generateScores()
    await data.loadOverview()
  }

  return {
    performanceNotice,
    generateCurrentMonthScores,
  }
}
