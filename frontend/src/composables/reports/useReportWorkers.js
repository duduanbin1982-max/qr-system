import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const TOP_N = 3

export function useReportWorkers(props) {
  const workers = ref([]); const loading = ref(true); const showTable = ref(false)
  const totalWorkers = ref(0)
  const canvas = ref(null)
  let chart = null

  async function load() {
    loading.value = true
    try {
      const d = await api.domains.stats.workerEfficiency({ start: props.start, end: props.end, product_code: props.productCode})
      const all = d.workers || []
      totalWorkers.value = all.length
      workers.value = all.slice(0, 15)
      await nextTick(); renderChart()
    } catch(e) {
      showToast('加载工人效率失败', 'error')
    } finally { loading.value = false }
  }

  function renderChart() {
    if (chart) { try { chart.destroy() } catch(e) {} }
    if (!canvas.value || !workers.value.length) return
    chart = new Chart(canvas.value.getContext('2d'), {
      type: 'bar',
      data: {
        labels: workers.value.map(w => w.name),
        datasets: [{
          label: '产量', data: workers.value.map(w => w.output || 0),
          backgroundColor: workers.value.map((_,i) => i < TOP_N ? '#F59E0B' : '#2563EB'),
          borderRadius: 4
        }]
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    })
  }

  onMounted(load)
  onUnmounted(() => { if (chart) { try { chart.destroy() } catch(e) {} } })

  return { workers, loading, showTable, totalWorkers, canvas, TOP_N }
}
