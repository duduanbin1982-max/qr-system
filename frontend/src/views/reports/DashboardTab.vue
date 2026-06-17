<template>
  <div>
    <!-- KPI Cards -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:var(--space-4);margin-bottom:var(--space-4)">
      <div class="card" style="text-align:center;padding:var(--space-4)">
        <div style="font-size:var(--text-3xl);font-weight:700;color:var(--primary)">{{ kpi.active_orders || 0 }}</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:4px">📋 在产订单</div>
      </div>
      <div class="card" style="text-align:center;padding:var(--space-4)">
        <div style="font-size:var(--text-3xl);font-weight:700;color:var(--success)">{{ kpi.completed_month || 0 }}</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:4px">✅ 本月完成</div>
      </div>
      <div class="card" style="text-align:center;padding:var(--space-4)">
        <div style="font-size:var(--text-3xl);font-weight:700;color:var(--warning)">{{ kpi.output_month || 0 }}</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:4px">📦 本月产量</div>
      </div>
      <div class="card" style="text-align:center;padding:var(--space-4)">
        <div style="font-size:var(--text-3xl);font-weight:700" :style="{color: (kpi.scrap_rate||0) > 0 ? 'var(--danger)' : 'var(--text-placeholder)'}">{{ kpi.scrap_rate || 0 }}%</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:4px">⚠️ 报废率</div>
      </div>
      <div class="card" style="text-align:center;padding:var(--space-4)">
        <div style="font-size:var(--text-3xl);font-weight:700;color:var(--primary)">{{ kpi.active_workers_today || 0 }}</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:4px">👷 今日在岗</div>
      </div>
      <div class="card" style="text-align:center;padding:var(--space-4)">
        <div style="font-size:var(--text-3xl);font-weight:700" :style="{color: (kpi.low_stock_count||0) > 0 ? 'var(--warning)' : 'var(--text-placeholder)'}">{{ kpi.low_stock_count || 0 }}</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:4px">📉 低库存</div>
      </div>
      <div class="card" style="text-align:center;padding:var(--space-4)">
        <div style="font-size:var(--text-3xl);font-weight:700;color:var(--text-placeholder)">{{ kpi.pending_shipments || 0 }}</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:4px">🚚 待发货</div>
      </div>
    </div>

    <!-- 7-Day Trend Mini Chart -->
    <div class="card" v-if="trendDates.length">
      <div class="card-header"><h3>📈 近7日产量趋势</h3></div>
      <div class="card-body"><div style="height:280px"><canvas ref="trendCanvas"></canvas></div></div>
    </div>
    <p v-else-if="!loading" class="empty"><span class="empty-text">暂无趋势数据</span></p>

    <!-- Monthly Summary -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="monthly">
      <div class="card-header"><h3>📅 本月汇总</h3></div>
      <div class="card-body">
        <div class="summary-bar" style="margin-bottom:var(--space-3)">
          <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val">{{ monthly.this_month?.orders || 0 }}</div><div class="s-label">本月订单</div></div></div>
          <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val text-success">{{ monthly.this_month?.output || 0 }}</div><div class="s-label">本月产量</div></div></div>
          <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-primary">{{ monthly.this_month?.completed_qty || 0 }}</div><div class="s-label">本月完成</div></div></div>
        </div>
        <div class="summary-bar">
          <div class="summary-item"><span class="s-icon">📊</span><div>
            <div class="s-val" :style="{color: (monthly.order_change_pct||0)>=0?'var(--success)':'var(--danger)'}">{{ monthly.order_change_pct != null ? (monthly.order_change_pct>=0?'+':'')+monthly.order_change_pct+'%' : '-' }}</div>
            <div class="s-label">订单环比</div>
          </div></div>
          <div class="summary-item"><span class="s-icon">📈</span><div>
            <div class="s-val" :style="{color: (monthly.output_change_pct||0)>=0?'var(--success)':'var(--danger)'}">{{ monthly.output_change_pct != null ? (monthly.output_change_pct>=0?'+':'')+monthly.output_change_pct+'%' : '-' }}</div>
            <div class="s-label">产量环比</div>
          </div></div>
          <div class="summary-item"><span class="s-icon">🎯</span><div>
            <div class="s-val" :style="{color: (monthly.completed_change_pct||0)>=0?'var(--success)':'var(--danger)'}">{{ monthly.completed_change_pct != null ? (monthly.completed_change_pct>=0?'+':'')+monthly.completed_change_pct+'%' : '-' }}</div>
            <div class="s-label">完成环比</div>
          </div></div>
        </div>
      </div>
    </div>
  </div>
</template>
<script>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  setup() {
    const kpi = ref({})
    const trendDates = ref([])
    const trendOutputs = ref([])
    const loading = ref(true)
    const trendCanvas = ref(null)
    const monthly = ref(null)
    let chartInstance = null

    async function load() {
      try {
        const kpiData = await api.dashboardKpi()
        kpi.value = kpiData
        const trend = kpiData.weekly_trend || []
        trendDates.value = trend.map(r => r.date)
        trendOutputs.value = trend.map(r => r.output || 0)
        if (kpiData.monthly_summary) {
          monthly.value = kpiData.monthly_summary
        }
        await nextTick()
        renderChart()
      } catch(e) {
        showToast('加载综合看板失败', 'error')
      } finally { loading.value = false }
    }

    function renderChart() {
      if (chartInstance) { chartInstance.destroy(); chartInstance = null }
      if (!trendCanvas.value || !trendDates.value.length) return
      const ctx = trendCanvas.value.getContext('2d')
      if (typeof Chart !== 'undefined') {
        chartInstance = new Chart(ctx, {
          type: 'line',
          data: {
            labels: trendDates.value,
            datasets: [{
              label: '日产量', data: trendOutputs.value,
              borderColor: '#2563EB', backgroundColor: 'rgba(37,99,235,0.1)',
              fill: true, tension: 0.3, pointRadius: 4
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
          }
        })
      }
    }

    onMounted(load)
    onUnmounted(() => { if (chartInstance) { chartInstance.destroy(); chartInstance = null } })

    return { kpi, trendDates, trendOutputs, loading, trendCanvas, monthly }
  }
}
</script>
