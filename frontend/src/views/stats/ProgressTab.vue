<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <h3>📈 在产订单进度</h3>
        <button class="btn btn-success btn-sm" @click="exportCsv" :disabled="!progressOrders.length">📥 CSV</button>
      </div>
    </div>
    <div v-if="progressOrders.length" class="summary-bar" style="margin-bottom:var(--space-4)">
      <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val text-primary">{{ progressStats.count }}</div><div class="s-label">在产订单</div></div></div>
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val" style="color:var(--primary)">{{ progressStats.qty }}</div><div class="s-label">总数量</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ progressStats.completed }}</div><div class="s-label">已完成</div></div></div>
      <div class="summary-item"><span class="s-icon">🎯</span><div><div class="s-val text-warning">{{ progressStats.near80 }}</div><div class="s-label">≥80%</div></div></div>
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val" style="color:var(--text-placeholder)">{{ progressStats.pending }}</div><div class="s-label">待开工</div></div></div>
    </div>
    <div class="card">
      <div class="card-header"><h3>📋 订单列表</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="progressOrders.length" class="data-table" style="font-size:var(--text-xs)">
        <thead><tr><th>#</th><th>订单号</th><th>客户</th><th>产品</th><th style="text-align:center">数量</th><th style="text-align:center">已完成</th><th>进度</th><th>状态</th></tr></thead>
        <tbody><tr v-for="(o,i) in progressOrders" :key="o.id" :class="o.status==='pending'?'row-dimmed':''">
          <td>{{ i+1 }}</td>
          <td><code style="font-size:var(--text-xs-alt)">{{ o.order_no }}</code></td>
          <td>{{ o.customer }}</td><td>{{ o.product_name }}</td>
          <td style="text-align:center">{{ o.quantity }}</td>
          <td style="text-align:center;color:var(--success)">{{ o.completed }}</td>
          <td>
            <div style="display:flex;align-items:center;gap:var(--space-1)">
              <div style="flex:1;height:6px;background:var(--bg-hover);border-radius:3px;overflow:hidden">
                <div :style="{width:progressPct(o)+'%', background: progressColor(o), height: '100%', borderRadius: '3px'}"></div>
              </div>
              <span style="font-size:var(--text-xs);font-weight:600;min-width:36px;text-align:right">{{ progressPct(o) }}%</span>
            </div>
          </td>
          <td><span class="badge" :class="statusBadge(o.status)">{{ statusLabel(o.status) }}</span></td>
        </tr></tbody>
      </table><p v-else class="empty">暂无在产订单</p></div></div>
    </div>
  </div>
</template>
<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV, statusLabel } from './shared.js'

function statusBadge(s) {
  const map = { pending: 'badge-info', producing: 'badge-warning', completed: 'badge-success', paused: 'badge-info', cancelled: 'badge-danger' }
  return map[s] || 'badge-info'
}

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    const progressOrders = ref([])
    const progressStats = computed(() => {
      const data = progressOrders.value
      return {
        count: data.length,
        qty: data.reduce((s,o) => s+(o.quantity||0), 0),
        completed: data.reduce((s,o) => s+(o.completed||0), 0),
        near80: data.filter(o => {
          const pct = o.quantity>0 ? Math.round((o.completed||0)/o.quantity*100) : 0
          return pct >= 80
        }).length,
        pending: data.filter(o => o.status === 'pending').length,
      }
    })
    function progressPct(o) { return o.quantity>0 ? Math.min(Math.round((o.completed||0)/o.quantity*100),100) : 0 }
    function progressColor(o) { const p=progressPct(o); return p>=100?'var(--success)':p>=50?'var(--primary)':'var(--warning)' }
    
    async function loadProgress() {
      try {
        const params = {}
        if (props.start) params.start = props.start
        if (props.end) params.end = props.end
        if (props.productCode) params.product_code = props.productCode
        const d = await api.orderProgress(params)
        progressOrders.value = d.orders || []
      } catch (e) { showToast(e.message, 'error') }
    }
    
    function exportCsv() {
      if (!progressOrders.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['#','订单号','客户','产品','数量','已完成','进度','状态']]
      progressOrders.value.forEach((o,i) => {
        data.push([i+1, o.order_no, o.customer, o.product_name, o.quantity, o.completed, progressPct(o)+'%', statusLabel(o.status)])
      })
      exportCSV(data, '订单进度表')
    }
    
    watch(() => [props.start, props.end, props.productCode], loadProgress)
    onMounted(loadProgress)
    return { progressOrders, progressStats, progressPct, progressColor, statusLabel, statusBadge, exportCsv }
  }
}
</script>
<style scoped>
.row-dimmed { opacity: 0.6; }
</style>
