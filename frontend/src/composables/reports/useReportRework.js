import { ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useReportRework(props) {
  const period = ref('week')
  const trendData = ref([])
  const processData = ref([])
  const workerData = ref([])
  const trendCanvas = ref(null)
  const processCanvas = ref(null)
  let trendChart = null
  let processChart = null

  async function loadTrend() {
    try {
      const d = await api.domains.rework.reworkTrend({ period: period.value, months: 6 })
      trendData.value = d.data || []
      await nextTick()
      renderTrendChart()
    } catch (e) { /* silent */ }
  }

  async function loadProcesses() {
    try {
      const d = await api.domains.rework.reworkTopProcesses({ n: 6 })
      processData.value = d.data || []
      await nextTick()
      renderProcessChart()
    } catch (e) { /* silent */ }
  }

  async function loadWorkers() {
    try {
      const d = await api.domains.rework.reworkWorkerStats()
      workerData.value = d.data || []
    } catch (e) { /* silent */ }
  }

  async function renderTrendChart() {
    if (!trendCanvas.value || !trendData.value.length) return
    if (trendChart) { trendChart.destroy(); trendChart = null }
    try {
      const { Chart, registerables } = await import('chart.js')
      Chart.register(...registerables)
      trendChart = new Chart(trendCanvas.value, {
        type: 'line',
        data: {
          labels: trendData.value.map(d => d.label),
          datasets: [
            { label: '返工件数', data: trendData.value.map(d => d.quantity), borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', fill: true, tension: 0.3 },
            { label: '返工次数', data: trendData.value.map(d => d.count), borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)', fill: true, tension: 0.3, yAxisID: 'y1' }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: {
            y: { title: { display: true, text: '件数' }, beginAtZero: true },
            y1: { position: 'right', title: { display: true, text: '次数' }, beginAtZero: true, grid: { drawOnChartArea: false } }
          },
          plugins: { legend: { position: 'top' } }
        }
      })
    } catch (e) { /* chart load failed */ }
  }

  async function renderProcessChart() {
    if (!processCanvas.value || !processData.value.length) return
    if (processChart) { processChart.destroy(); processChart = null }
    try {
      const { Chart, registerables } = await import('chart.js')
      Chart.register(...registerables)
      processChart = new Chart(processCanvas.value, {
        type: 'bar',
        data: {
          labels: processData.value.map(d => d.process_name),
          datasets: [
            { label: '返工率 (%)', data: processData.value.map(d => d.rate), backgroundColor: processData.value.map(d => d.rate > 10 ? '#ef4444' : d.rate > 5 ? '#f59e0b' : '#10b981') }
          ]
        },
        options: {
          indexAxis: 'y',
          responsive: true, maintainAspectRatio: false,
          scales: { x: { title: { display: true, text: '返工率 (%)' }, beginAtZero: true } },
          plugins: { legend: { display: false } }
        }
      })
    } catch (e) { /* chart load failed */ }
  }

  function destroyCharts() {
    if (trendChart) { trendChart.destroy(); trendChart = null }
    if (processChart) { processChart.destroy(); processChart = null }
  }

  function loadAll() {
    loadTrend()
    loadProcesses()
    loadWorkers()
  }

  onMounted(loadAll)
  watch(() => props.refreshKey, loadAll)
  onBeforeUnmount(destroyCharts)

  return { period, trendData, processData, workerData, trendCanvas, processCanvas }
}
