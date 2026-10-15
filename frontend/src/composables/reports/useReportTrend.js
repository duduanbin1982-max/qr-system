import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useReportTrend() {
  const days = ref(30)
  const loading = ref(true)
  const summary = ref({})
  const trendDates = ref([])
  const trendOutputs = ref([])
  const trendScraps = ref([])
  const processLabels = ref([])
  const processData = ref([])
  const lineCanvas = ref(null); const barCanvas = ref(null)
  let lineChart = null; let barChart = null

  async function load() {
    loading.value = true
    try {
      const now = new Date()
      const fmt = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0')
      const endDate = fmt(now)
      const startDate = fmt(new Date(now - (days.value - 1) * 86400000))
      const [tRes, qRes] = await Promise.all([
        api.domains.stats.productionTrend({ days: days.value }),
        api.domains.stats.qualityAnalysis({ start: startDate, end: endDate })
      ])
      const trend = tRes.trend || []
      summary.value = tRes.summary || {}
      trendDates.value = trend.map(r => r.date)
      trendOutputs.value = trend.map(r => r.output || 0)
      trendScraps.value = trend.map(r => r.scrap || 0)
      const bp = qRes.by_process || []
      processLabels.value = bp.map(p => p.name)
      processData.value = bp.map(p => p.output || 0)
      await nextTick()
      renderLine()
      renderBar()
    } catch(e) {
      showToast('加载产量趋势失败', 'error')
    } finally { loading.value = false }
  }

  function renderLine() {
    if (lineChart) lineChart.destroy()
    if (!lineCanvas.value || !trendDates.value.length) return
    lineChart = new Chart(lineCanvas.value.getContext('2d'), {
      type: 'line',
      data: {
        labels: trendDates.value,
        datasets: [
          { label: '产量', data: trendOutputs.value, borderColor: '#2563EB', backgroundColor: 'rgba(37,99,235,0.1)', fill: true, tension: 0.3, pointRadius: 3 },
          { label: '报废', data: trendScraps.value, borderColor: '#EF4444', backgroundColor: 'rgba(239,68,68,0.1)', fill: true, tension: 0.3, pointRadius: 3, borderDash: [5,3] }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position:'top' } }, scales: { y: { beginAtZero: true, ticks:{precision:0} } } }
    })
  }

  function renderBar() {
    if (barChart) barChart.destroy()
    if (!barCanvas.value || !processLabels.value.length) return
    barChart = new Chart(barCanvas.value.getContext('2d'), {
      type: 'bar',
      data: {
        labels: processLabels.value,
        datasets: [{ label: '产量', data: processData.value, backgroundColor: '#2563EB', borderRadius: 6 }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display:false } }, scales: { y: { beginAtZero: true, ticks:{precision:0} } } }
    })
  }

  onMounted(load)
  onUnmounted(() => { if (lineChart) lineChart.destroy(); if (barChart) barChart.destroy() })

  return { days, loading, summary, trendDates, trendOutputs, trendScraps, processLabels, processData, lineCanvas, barCanvas }
}
