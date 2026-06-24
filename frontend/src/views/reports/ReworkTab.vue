<template>
  <div>
    <!-- Line Chart: Rework Trend -->
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;align-items:center;justify-content:space-between">
        <h3>📈 返工趋势</h3>
        <div style="display:flex;gap:8px">
          <button v-for="p in ['week','month']" :key="p" @click="period=p;loadTrend()"
            class="btn-sm" :style="{background:period===p?'var(--primary)':'var(--bg-hover)',color:period===p?'#fff':'var(--text-placeholder)',border:'none',padding:'4px 12px',borderRadius:'6px',cursor:'pointer'}">
            {{ p==='week'?'按周':'按月' }}
          </button>
        </div>
      </div>
      <div class="card-body">
        <div v-if="trendData.length" style="height:300px"><canvas ref="trendCanvas"></canvas></div>
        <div v-else style="text-align:center;padding:60px;color:var(--text-placeholder)">暂无返工趋势数据</div>
      </div>
    </div>

    <!-- Top Processes by Rework Rate -->
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header"><h3>🔧 工序返工率排行 (Top {{ processData.length }})</h3></div>
      <div class="card-body">
        <div v-if="processData.length" style="height:280px"><canvas ref="processCanvas"></canvas></div>
        <div v-else style="text-align:center;padding:60px;color:var(--text-placeholder)">暂无工序返工数据</div>
      </div>
    </div>

    <!-- Worker Rework Table -->
    <div class="card">
      <div class="card-header"><h3>👷 工人返工统计</h3></div>
      <div class="card-body">
        <div v-if="workerData.length" style="overflow-x:auto">
          <table class="table">
            <thead><tr>
              <th>工人</th><th>返工次数</th><th>返工件数</th><th>涉及订单</th>
              <th>返工率</th><th>报废件数</th><th>平均耗时(h)</th>
            </tr></thead>
            <tbody>
              <tr v-for="w in workerData" :key="w.worker_id">
                <td style="font-weight:600">{{ w.worker_name }}</td>
                <td>{{ w.rework_count }}</td>
                <td>{{ w.rework_qty }}</td>
                <td>{{ w.affected_orders }}</td>
                <td>
                  <span :style="{color: w.rate > 10 ? 'var(--danger)' : w.rate > 5 ? 'var(--warning)' : 'var(--success)', fontWeight:600}">
                    {{ w.rate }}%
                  </span>
                </td>
                <td>{{ w.scrap_qty }}</td>
                <td>{{ w.avg_duration || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else style="text-align:center;padding:60px;color:var(--text-placeholder)">暂无工人返工数据</div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  props: { refreshKey: { type: Number, default: 0 } },
  setup(props) {
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
        const d = await api.reworkTrend({ period: period.value, months: 6 })
        trendData.value = d.data || []
        await nextTick()
        renderTrendChart()
      } catch (e) { /* silent */ }
    }

    async function loadProcesses() {
      try {
        const d = await api.reworkTopProcesses({ n: 6 })
        processData.value = d.data || []
        await nextTick()
        renderProcessChart()
      } catch (e) { /* silent */ }
    }

    async function loadWorkers() {
      try {
        const d = await api.reworkWorkerStats()
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
}
</script>
