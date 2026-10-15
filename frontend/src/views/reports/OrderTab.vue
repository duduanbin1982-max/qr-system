<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header"><h3>🥧 订单状态分布</h3></div>
      <div class="card-body">
        <div style="height:340px"><canvas ref="pieCanvas"></canvas></div>
        <div v-if="completionRate !== null" style="text-align:center;margin-top:var(--space-3);font-size:var(--text-sm);color:var(--text-placeholder)">
          整体完成率：<strong style="color:var(--primary)">{{ completionRate }}%</strong>（已完成 {{ totalDone }} / 总计 {{ totalQty }} 件）
        </div>
      </div>
    </div>
    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <p v-if="!byStatus.length && !loading" class="empty"><span class="empty-text">暂无订单数据</span></p>
    <div class="card" v-if="monthly.length">
      <div class="card-header"><h3>📊 月度订单趋势</h3></div>
      <div class="card-body"><div style="height:320px"><canvas ref="barCanvas"></canvas></div></div>
    </div>
  </div>
</template>
<script>
import { useReportOrders } from '@/composables/reports/useReportOrders.js'

export default {
  setup() {
    return useReportOrders()
  }
}
</script>
