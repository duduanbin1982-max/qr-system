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
import { useProgressStats } from '@/composables/stats/useProgressStats.js'

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    return useProgressStats(props)
  }
}
</script>
<style scoped>
.row-dimmed { opacity: 0.6; }
</style>
