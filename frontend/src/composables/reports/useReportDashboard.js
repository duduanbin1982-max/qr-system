import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useReportDashboard() {
  const kpi = ref({})
  const trendDates = ref([])
  const trendOutputs = ref([])
  const loading = ref(true)
  const trendCanvas = ref(null)
  const monthly = ref(null)
  let chartInstance = null

  async function load() {
    try {
      const kpiData = await api.domains.stats.dashboardKpi()
      kpi.value = kpiData
      const trend = kpiData.weekly_trend || []
      trendDates.value = trend.map(r => r.date)
      trendOutputs.value = trend.map(r => r.output || 0)
      if (kpiData.monthly_summary) {
        monthly.value = kpiData.monthly_summary
      }
      await nextTick()
      renderChart()
    } catch(e) {
      showToast('加载综合看板失败', 'error')
    } finally { loading.value = false }
  }

  function renderChart() {
    if (chartInstance) { chartInstance.destroy(); chartInstance = null }
    if (!trendCanvas.value || !trendDates.value.length) return
    const ctx = trendCanvas.value.getContext('2d')
    if (typeof Chart !== 'undefined') {
      chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
          labels: trendDates.value,
          datasets: [{
            label: '日产量', data: trendOutputs.value,
            borderColor: '#2563EB', backgroundColor: 'rgba(37,99,235,0.1)',
            fill: true, tension: 0.3, pointRadius: 4
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      })
    }
  }

  onMounted(load)
  onUnmounted(() => { if (chartInstance) { chartInstance.destroy(); chartInstance = null } })

  return { kpi, trendDates, trendOutputs, loading, trendCanvas, monthly }
}
