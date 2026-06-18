<!-- TrendTab.vue -->
<template>
<div v-if="activeTab==='trend'">
      <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
        <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) 20px">
          <h3 style="font-size:var(--text-lg);font-weight:700;margin:0">📈 工资趋势</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto">
            <select v-model="trendMonths" class="form-input" style="width:120px;font-size:var(--text-sm)">
              <option :value="6">近6月</option>
              <option :value="12">近12月</option>
              <option :value="24">近24月</option>
            </select>
            <button class="btn-primary btn-sm" @click="loadTrends">刷新</button>
          </div>
        </div>
        <div v-if="trendLoading" style="text-align:center;padding:60px">⏳ 加载中...</div>
        <div v-else-if="!trendData.length" style="text-align:center;padding:60px;color:var(--text-placeholder)">
          <p style="font-size:48px;margin:0">📈</p>
          <p style="margin-top:12px">暂无趋势数据，请先在计件工资中保存月度快照</p>
        </div>
        <div v-else style="padding:20px">
          <div style="height:320px;position:relative">
            <canvas ref="trendChartRef"></canvas>
          </div>
          <div style="display:flex;gap:20px;margin-top:16px;justify-content:center">
            <div class="summary-item"><span class="s-icon">📊</span><div><div class="s-val text-primary">¥{{ trendAvg() }}</div><div class="s-label">月均工资 (元)</div></div></div>
            <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val text-success">{{ trendTotalQty() }}</div><div class="s-label">累计件数</div></div></div>
            <div class="summary-item"><span class="s-icon">💰</span><div><div class="s-val" style="color:var(--warning)">¥{{ fmtMoney(trendTotal()) }}</div><div class="s-label">累计工资</div></div></div>
          </div>
        </div>
      </div>
    </div>
</template>

<script>
import { useWage } from '@/composables/useWage.js'

export default {
  setup() {
    return { ...useWage() }
  }
}
</script>
