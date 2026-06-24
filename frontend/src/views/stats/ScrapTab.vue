<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <h3>⚠️ 报废记录</h3>
        <button class="btn btn-success btn-sm" @click="exportCsv" :disabled="!records.length">📥 CSV</button>
      </div>
    </div>
    <div v-if="summary.total_records" class="summary-bar" style="margin-bottom:var(--space-4)">
      <div class="summary-item"><span class="s-icon">🗑️</span><div><div class="s-val text-danger">{{ summary.total_records }}</div><div class="s-label">报废次数</div></div></div>
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val" style="color:var(--danger)">{{ summary.total_qty }}</div><div class="s-label">报废数量</div></div></div>
      <div class="summary-item"><span class="s-icon">🔧</span><div><div class="s-val text-warning">{{ summary.process_count }}</div><div class="s-label">涉及工序</div></div></div>
    </div>
    <div class="card" style="margin-bottom:var(--space-4)" v-if="byProcess.length">
      <div class="card-header"><h3>📊 报废工序排行</h3></div>
      <div class="card-body"><div class="table-wrap"><table class="data-table">
        <thead><tr><th style="width:40px">#</th><th>工序</th><th style="text-align:center">报废次数</th><th style="text-align:center">报废数量</th></tr></thead>
        <tbody><tr v-for="(p,i) in byProcess" :key="i">
          <td>{{ i+1 }}</td><td style="font-weight:500">{{ p.name }}</td>
          <td style="text-align:center;color:var(--danger)">{{ p.cnt }}</td>
          <td style="text-align:center;color:var(--danger);font-weight:600">{{ p.qty }}</td>
        </tr></tbody>
      </table></div></div>
    </div>
    <!-- P1: scrap reason distribution -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="reasonData.labels.length">
      <div class="card-header"><h3>🥧 报废原因分布</h3></div>
      <div class="card-body" style="height:300px"><canvas ref="reasonChart"></canvas></div>
    </div>
    <div class="card"><div class="card-header"><h3>📋 报废列表</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="records.length" class="data-table" style="font-size:var(--text-xs)">
        <thead><tr><th>订单号</th><th>产品</th><th>工序</th><th>工人</th><th style="text-align:center">数量</th><th>原因</th><th>时间</th></tr></thead>
        <tbody><tr v-for="r in records" :key="r.id">
          <td><code style="font-size:var(--text-xs-alt)">{{ r.order_no }}</code></td>
          <td>{{ r.product_name }}</td><td>{{ r.process_name }}</td>
          <td>{{ r.worker_name }}<span v-if="r.employee_no" style="color:var(--text-placeholder);font-size:var(--text-2xs)"> #{{ r.employee_no }}</span></td>
          <td style="text-align:center;color:var(--danger);font-weight:600">{{ r.quantity }}</td>
          <td>{{ r.reason || '-' }}</td>
          <td style="font-size:var(--text-xs-alt);white-space:nowrap">{{ r.created_at }}</td>
        </tr></tbody>
      </table><p v-else class="empty">📭 暂无报废记录</p></div></div>
    </div>
  </div>
</template>
<script>
import { ref, watch, onMounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV } from './shared.js'
export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
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
        const d = await api.scrapStats(params)
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
}
</script>
