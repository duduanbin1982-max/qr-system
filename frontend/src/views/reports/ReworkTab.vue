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
import { useReportRework } from '@/composables/reports/useReportRework.js'

export default {
  props: { refreshKey: { type: Number, default: 0 } },
  setup(props) {
    return useReportRework(props)
  }
}
</script>
