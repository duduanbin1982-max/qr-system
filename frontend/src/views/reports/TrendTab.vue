<template>
  <div>
    <!-- Date Filter -->
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;gap:var(--space-2);align-items:center;flex-wrap:wrap">
        <h3>📈 产量趋势</h3>
        <span style="color:var(--text-placeholder);font-size:var(--text-sm)">最近</span>
        <select class="form-input" v-model.number="days" @change="load" style="width:120px">
          <option :value="7">7 天</option>
          <option :value="14">14 天</option>
          <option :value="30">30 天</option>
          <option :value="60">60 天</option>
          <option :value="90">90 天</option>
        </select>
        <span v-if="summary.total_output" style="margin-left:auto;color:var(--text-placeholder);font-size:var(--text-sm)">
          累计产量 <b style="color:var(--primary)">{{ summary.total_output }}</b> 件
        </span>
      </div>
    </div>

    <!-- Line Chart -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="trendDates.length">
      <div class="card-header"><h3>📈 日产量趋势</h3></div>
      <div class="card-body"><div style="height:360px"><canvas ref="lineCanvas"></canvas></div></div>
    </div>

    <!-- Bar Chart: By Process -->
    <div class="card" v-if="processLabels.length">
      <div class="card-header"><h3>📊 工序产量分布</h3></div>
      <div class="card-body"><div style="height:320px"><canvas ref="barCanvas"></canvas></div></div>
    </div>

    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <p v-if="!trendDates.length && !loading" class="empty"><span class="empty-text">暂无数据</span></p>
  </div>
</template>
<script>
import { useReportTrend } from '@/composables/reports/useReportTrend.js'

export default {
  setup() {
    return useReportTrend()
  }
}
</script>
