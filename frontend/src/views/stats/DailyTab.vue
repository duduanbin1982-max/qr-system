<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <h3>📊 生产日报表</h3>
        <div v-if="canExport" style="display:flex;gap:var(--space-2)">
          <button class="btn btn-outline btn-sm" @click="exportSummaryCsv" :disabled="!dailySummary.length">📥 导出汇总</button>
          <button class="btn btn-outline btn-sm" @click="exportDetailCsv" :disabled="!dailyRecords.length">📥 导出明细</button>
        </div>
      </div>
    </div>
    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <div class="card" style="margin-bottom:var(--space-4)" v-if="dailySummary.length">
      <div class="card-header"><h3>📊 工序汇总</h3></div>
      <div class="card-body"><div class="table-wrap"><table class="data-table">
        <thead><tr><th style="width:40px">#</th><th>工序</th><th style="text-align:center">报工次数</th><th style="text-align:center">产出</th><th style="text-align:center">报废</th><th style="text-align:center">返修</th></tr></thead>
        <tbody><tr v-for="(s, idx) in dailySummary" :key="s.id">
          <td><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ idx+1 }}</span></td>
          <td style="font-weight:500">{{ s.name }}</td>
          <td style="text-align:center">{{ s.record_count }}</td>
          <td style="text-align:center"><span class="badge" style="background:var(--success-light);color:var(--success-dark);border:1px solid var(--success-lighter)">{{ s.total_output }}</span></td>
          <td style="text-align:center"><span class="badge" style="background:var(--danger-light);color:var(--danger);border:1px solid var(--danger-lighter)">{{ s.total_scrap }}</span></td>
          <td style="text-align:center"><span class="badge" style="background:var(--warning-light);color:var(--warning);border:1px solid var(--warning-lighter)">{{ s.total_rework }}</span></td>
        </tr></tbody>
      </table></div></div>
    </div>
    <div class="card">
      <div class="card-header"><h3>📝 报工明细 ({{ dailyRecords.length }})</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="dailyRecords.length" class="data-table" style="font-size:var(--text-xs)">
        <thead><tr><th>时间</th><th>订单号</th><th>产品</th><th>工序</th><th>工人</th><th style="text-align:center">数量</th><th>类型</th></tr></thead>
        <tbody><tr v-for="r in dailyRecords" :key="r.id">
          <td style="font-size:var(--text-xs-alt);white-space:nowrap">{{ r.created_at }}</td>
          <td><code style="font-size:var(--text-xs-alt)">{{ r.order_no }}</code></td>
          <td>{{ r.product_name }}</td><td>{{ r.process_name }}</td>
          <td>{{ r.worker_name }}<span v-if="r.employee_no" style="color:var(--text-placeholder);font-size:var(--text-2xs)"> #{{ r.employee_no }}</span></td>
          <td style="text-align:center;font-weight:600">{{ r.quantity }}</td>
          <td><span class="badge" :class="r.type==='normal'?'badge-success':r.type==='scrap'?'badge-danger':'badge-warning'" style="font-size:var(--text-2xs)">{{ r.type==='normal'?'正常':r.type==='scrap'?'报废':'返工' }}</span></td>
        </tr></tbody>
      </table><p v-else class="empty">📭 该日期无报工记录（仅显示已审批通过的记录）</p></div></div>
    </div>
  </div>
</template>
<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
import { exportCSV } from './shared.js'
export default {
  props: { date: { type: String, default: '' }, productCode: { type: String, default: '' } },
  setup(props) {
    const dailyRecords = ref([]); const dailySummary = ref([]); const loading = ref(true)
    const canExport = computed(() => can('stats:view'))

    function isValidDate(str) {
      if (!str) return true
      if (!/^\d{4}-\d{2}-\d{2}$/.test(str)) return false
      const [y, m, d] = str.split('-').map(Number)
      const dt = new Date(y, m - 1, d)
      return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d
    }

    async function loadDaily() {
      const d = props.date || new Date().toISOString().slice(0, 10)
      if (!isValidDate(d)) {
        showToast('日期格式无效', 'warning')
        return
      }
      try {
        const params = { date: d }
        if (props.productCode) params.product_code = props.productCode
        const res = await api.dailyStats(params)
        dailyRecords.value = res.records || []; dailySummary.value = res.summary || []
      } catch (e) { showToast(e.message, 'error') } finally { loading.value = false }
    }

    function exportSummaryCsv() {
      if (!dailySummary.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['工序','报工次数','产出','报废','返修']]
      dailySummary.value.forEach(s => data.push([s.name, s.record_count, s.total_output, s.total_scrap, s.total_rework]))
      exportCSV(data, '日报表_工序汇总_' + (props.date || ''))
    }

    function exportDetailCsv() {
      if (!dailyRecords.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['时间','订单号','产品','工序','工人','工号','数量','类型']]
      dailyRecords.value.forEach(r => data.push([r.created_at, r.order_no, r.product_name, r.process_name, r.worker_name, r.employee_no||'', r.quantity, r.type==='normal'?'正常':r.type==='scrap'?'报废':'返工']))
      exportCSV(data, '日报表_报工明细_' + (props.date || ''))
    }

    onMounted(loadDaily)
    return { dailyRecords, dailySummary, loading, loadDaily, exportSummaryCsv, exportDetailCsv, canExport }
  }
}
</script>
