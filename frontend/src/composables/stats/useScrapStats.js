import { ref, watch, onMounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV } from '@/composables/reports/reportSupport.js'

export function useScrapStats(props) {
  const records = ref([])
  const summary = ref({})
  const byProcess = ref([])
  const reasonChart = ref(null)
  const reasonData = ref({ labels: [], values: [] })
  let chartInstance = null

  async function buildReasonData() {
    const reasonMap = {}
    records.value.forEach(r => {
      const key = r.reason || '未填写'
      reasonMap[key] = (reasonMap[key] || 0) + (r.quantity || 1)
    })
    reasonData.value = {
      labels: Object.keys(reasonMap),
      values: Object.values(reasonMap)
    }
    await nextTick()
    if (reasonChart.value) renderPie()
  }

  function renderPie() {
    if (chartInstance) chartInstance.destroy()
    const ctx = reasonChart.value?.getContext('2d')
    if (!ctx || !reasonData.value.labels.length) return
    const colors = ['#ef4444','#f59e0b','#3b82f6','#10b981','#8b5cf6','#ec4899','#06b6d4','#f97316']
    chartInstance = new Chart(ctx, {
      type: 'pie',
      data: {
        labels: reasonData.value.labels,
        datasets: [{ data: reasonData.value.values, backgroundColor: colors.slice(0, reasonData.value.labels.length) }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } }
    })
  }

  async function loadScrap() {
    try {
      const params = {}
      if (props.start) params.start = props.start
      if (props.end) params.end = props.end
      if (props.productCode) params.product_code = props.productCode
      const d = await api.domains.stats.scrapStats(params)
      records.value = d.records || []
      summary.value = d.summary || {}
      byProcess.value = d.by_process || []
      await buildReasonData()
    } catch (e) { showToast(e.message, 'error') }
  }
  function exportCsv() {
    if (!records.value.length) { showToast('没有数据可导出', 'warning'); return }
    const data = [['订单号','产品','工序','工人','工号','数量','原因','时间']]
    records.value.forEach(r => data.push([r.order_no, r.product_name, r.process_name, r.worker_name, r.employee_no||'', r.quantity, r.reason||'', r.created_at]))
    const dateTag = props.start ? props.start + '_' + (props.end || '') : new Date().toISOString().slice(0, 10); exportCSV(data, '报废记录_' + dateTag)
  }
  watch(() => [props.start, props.end, props.productCode], loadScrap)
  onMounted(loadScrap)
  return { records, summary, byProcess, exportCsv, reasonChart, reasonData }
}
