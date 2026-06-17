<template>
  <div>
    <!-- Pie: Quality Ratio -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="hasData">
      <div class="card-header"><h3>🥧 良品/报废比例</h3></div>
      <div class="card-body"><div style="height:340px"><canvas ref="pieCanvas"></canvas></div></div>
    </div>

    <!-- Horizontal Bar: Scrap by Process -->
    <div class="card" v-if="byProcess.length" style="margin-bottom:var(--space-4)">
      <div class="card-header"><h3>📊 各工序报废排行</h3></div>
      <div class="card-body"><div style="height:320px"><canvas ref="hBarCanvas"></canvas></div></div>
    </div>

    <!-- Trend: Pass Rate over time -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="trendLabels.length">
      <div class="card-header"><h3>📈 合格率趋势</h3></div>
      <div class="card-body"><div style="height:280px"><canvas ref="trendCanvas"></canvas></div></div>
    </div>

    <!-- SPC P-Chart -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="spcSamples.length">
      <div class="card-header" style="display:flex;align-items:center;justify-content:space-between">
        <h3>📊 SPC 不合格率控制图 (P 图)</h3>
        <span style="font-size:var(--text-xs);color:var(--text-placeholder)">UCL: {{ spcUcl }}% | CL: {{ spcCl }}% | LCL: {{ spcLcl }}%</span>
      </div>
      <div class="card-body"><div style="height:300px"><canvas ref="spcCanvas"></canvas></div></div>
    </div>

    <!-- Inspector Performance -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="inspectorData.length">
      <div class="card-header"><h3>👨‍🔧 检验员绩效</h3></div>
      <div class="card-body" style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>检验员</th><th>检验次数</th><th>检验总数</th><th>不合格数</th><th>缺陷率</th><th>涉及订单</th></tr></thead>
          <tbody>
            <tr v-for="ins in inspectorData" :key="ins.inspector_id">
              <td style="font-weight:600">{{ ins.inspector_name }}</td>
              <td>{{ ins.inspection_count }}</td>
              <td>{{ ins.total_checked }}</td>
              <td>{{ ins.total_failed }}</td>
              <td><span :style="{color:ins.overall_defect_rate>20?'var(--danger)':ins.overall_defect_rate>10?'var(--warning)':'var(--success)',fontWeight:600}">{{ ins.overall_defect_rate }}%</span></td>
              <td>{{ ins.orders_covered }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Supplier Quality -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="supplierData.length">
      <div class="card-header"><h3>🏭 供应商(客户)质量分析</h3></div>
      <div class="card-body" style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>供应商/客户</th><th>检验次数</th><th>检验总数</th><th>不合格数</th><th>缺陷率</th><th>合格率</th></tr></thead>
          <tbody>
            <tr v-for="sup in supplierData" :key="sup.customer_id">
              <td style="font-weight:600">{{ sup.customer_name }}</td>
              <td>{{ sup.inspection_count }}</td>
              <td>{{ sup.total_checked }}</td>
              <td>{{ sup.total_failed }}</td>
              <td><span :style="{color:sup.defect_rate>15?'var(--danger)':sup.defect_rate>8?'var(--warning)':'var(--success)',fontWeight:600}">{{ sup.defect_rate }}%</span></td>
              <td><span :style="{color:sup.pass_rate<85?'var(--danger)':sup.pass_rate<95?'var(--warning)':'var(--success)',fontWeight:600}">{{ sup.pass_rate }}%</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Defect Rate Table -->
    <div class="card" v-if="byProcess.length">
      <div class="card-header"><h3>📋 工序缺陷率明细</h3></div>
      <div class="card-body">
        <div style="overflow-x:auto">
          <table class="table">
            <thead><tr><th>工序</th><th>产量</th><th>报废</th><th>返工</th><th>缺陷率</th></tr></thead>
            <tbody>
              <tr v-for="p in byProcess" :key="p.id">
                <td>{{ p.name }}</td><td>{{ p.output||0 }}</td><td>{{ p.scrap||0 }}</td><td>{{ p.rework||0 }}</td>
                <td :style="{color: (p.defect_rate||0) > 5 ? 'var(--danger)' : (p.defect_rate||0) > 2 ? 'var(--warning)' : 'var(--success)'}">{{ p.defect_rate != null ? p.defect_rate+'%' : '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <p v-if="!hasData && !loading" class="empty"><span class="empty-text">暂无品质数据</span></p>
  </div>
</template>
<script>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    const byProcess = ref([])
    const loading = ref(true)
    const pieCanvas = ref(null)
    const hBarCanvas = ref(null)
    const trendCanvas = ref(null)
    const spcCanvas = ref(null)
    const trendLabels = ref([])
    const trendPassRates = ref([])
    const spcSamples = ref([])
    const spcUcl = ref(0)
    const spcCl = ref(0)
    const spcLcl = ref(0)
    const inspectorData = ref([])
    const supplierData = ref([])

    let pieChart = null
    let hBarChart = null
    let trendChart = null
    let spcChart = null

    const hasData = computed(() => byProcess.value.some(p => (p.output||0)+(p.scrap||0)+(p.rework||0) > 0))

    function safeChart(ChartClass) {
      return typeof Chart !== 'undefined' ? ChartClass : null
    }

    async function load() {
      loading.value = true
      try {
        const params = {}
        if (props.start) params.start = props.start
        if (props.end) params.end = props.end
        if (props.productCode) params.product_code = props.productCode
        const d = await api.qualityAnalysis(params)
        byProcess.value = (d.by_process || []).sort((a,b) => (b.scrap||0) - (a.scrap||0))

        // Optional extra data
        trendLabels.value = d.trend_labels || []
        trendPassRates.value = d.trend_pass_rates || []
        spcSamples.value = d.spc_samples || []
        spcUcl.value = d.spc_ucl || 0
        spcCl.value = d.spc_cl || 0
        spcLcl.value = d.spc_lcl || 0
        inspectorData.value = d.inspector_data || []
        supplierData.value = d.supplier_data || []

        await nextTick()
        renderPie()
        renderHBar()
        renderTrend()
        renderSpc()
      } catch(e) {
        showToast('加载品质分析失败', 'error')
      } finally { loading.value = false }
    }

    function renderPie() {
      if (pieChart) { pieChart.destroy(); pieChart = null }
      if (!pieCanvas.value || typeof Chart === 'undefined') return
      const totalOk = byProcess.value.reduce((s,p)=>s+(p.output||0), 0)
      const totalScrap = byProcess.value.reduce((s,p)=>s+(p.scrap||0), 0)
      const totalRework = byProcess.value.reduce((s,p)=>s+(p.rework||0), 0)
      if (totalOk + totalScrap + totalRework === 0) return
      const slices = [
        { label: '良品', value: totalOk, color: '#22C55E' },
        { label: '返工', value: totalRework, color: '#F59E0B' },
        { label: '报废', value: totalScrap, color: '#EF4444' },
      ].filter(s => s.value > 0)
      pieChart = new Chart(pieCanvas.value.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels: slices.map(s => s.label),
          datasets: [{ data: slices.map(s => s.value), backgroundColor: slices.map(s => s.color), borderWidth: 0 }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position:'bottom' }, tooltip: { callbacks: { label: ctx => ctx.label+': '+ctx.raw+' 件' } } }
        }
      })
    }

    function renderHBar() {
      if (hBarChart) { hBarChart.destroy(); hBarChart = null }
      if (!hBarCanvas.value || !byProcess.value.length || typeof Chart === 'undefined') return
      hBarChart = new Chart(hBarCanvas.value.getContext('2d'), {
        type: 'bar',
        data: {
          labels: byProcess.value.map(p=>p.name),
          datasets: [{
            label: '报废数', data: byProcess.value.map(p=>p.scrap||0),
            backgroundColor: '#EF4444', borderRadius: 4
          }]
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display:false } },
          scales: { x: { beginAtZero: true, ticks:{precision:0} } }
        }
      })
    }

    function renderTrend() {
      if (trendChart) { trendChart.destroy(); trendChart = null }
      if (!trendCanvas.value || !trendLabels.value.length || typeof Chart === 'undefined') return
      trendChart = new Chart(trendCanvas.value.getContext('2d'), {
        type: 'line',
        data: {
          labels: trendLabels.value,
          datasets: [{
            label: '合格率 %', data: trendPassRates.value,
            borderColor: '#22C55E', backgroundColor: 'rgba(34,197,94,0.1)',
            fill: true, tension: 0.3, pointRadius: 3
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { y: { min: 0, max: 100, ticks: { callback: v => v+'%' } } }
        }
      })
    }

    function renderSpc() {
      if (spcChart) { spcChart.destroy(); spcChart = null }
      if (!spcCanvas.value || !spcSamples.value.length || typeof Chart === 'undefined') return
      spcChart = new Chart(spcCanvas.value.getContext('2d'), {
        type: 'line',
        data: {
          labels: spcSamples.value.map((_, i) => '样本'+(i+1)),
          datasets: [
            { label: '不合格率 %', data: spcSamples.value, borderColor: '#2563EB', pointRadius: 3 },
            { label: 'UCL', data: spcSamples.value.map(() => spcUcl.value), borderColor: '#EF4444', borderDash: [5,5], pointRadius: 0, fill: false },
            { label: 'CL', data: spcSamples.value.map(() => spcCl.value), borderColor: '#F59E0B', borderDash: [3,3], pointRadius: 0, fill: false },
            { label: 'LCL', data: spcSamples.value.map(() => spcLcl.value), borderColor: '#22C55E', borderDash: [5,5], pointRadius: 0, fill: false }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom' } },
          scales: { y: { beginAtZero: true } }
        }
      })
    }

    function destroyAll() {
      [pieChart, hBarChart, trendChart, spcChart].forEach(c => { if (c) c.destroy() })
      pieChart = hBarChart = trendChart = spcChart = null
    }

    watch(() => [props.start, props.end, props.productCode], load)
    onMounted(load)
    onUnmounted(destroyAll)

    return {
      byProcess, hasData, loading,
      pieCanvas, hBarCanvas, trendCanvas, spcCanvas,
      trendLabels, spcSamples, spcUcl, spcCl, spcLcl,
      inspectorData, supplierData
    }
  }
}
</script>
