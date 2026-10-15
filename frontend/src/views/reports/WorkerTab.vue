<template>
  <div>
    <div class="card" v-if="workers.length">
      <div class="card-header"><h3>👷 工人效率排行</h3></div>
      <div class="card-body">
        <div style="height:480px"><canvas ref="canvas"></canvas></div>
        <div v-if="totalWorkers > 15" style="text-align:center;margin-top:var(--space-2);font-size:var(--text-xs);color:var(--text-placeholder)">
          显示前 15 名，共 {{ totalWorkers }} 名工人
        </div>
      </div>
    </div>

    <!-- Data Table -->
    <div class="card" v-if="workers.length" style="margin-top:var(--space-4)">
      <div class="card-header">
        <h3>📋 工人效率排行（前 15 名）</h3>
        <button class="btn btn-sm" @click="showTable = !showTable" style="font-size:var(--text-xs)">
          {{ showTable ? '收起' : '展开' }}
        </button>
      </div>
      <div class="card-body" v-if="showTable">
        <div style="overflow-x:auto">
          <table class="table">
            <thead>
              <tr>
                <th>排名</th><th>姓名</th><th>工号</th><th>产量</th><th>报废</th><th>返工</th>
                <th>报废率</th><th>返工率</th><th>出勤天数</th><th>日均产量</th><th>报工次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(w,i) in workers" :key="w.id" :style="{background: i<TOP_N ? 'var(--bg-highlight)' : ''}">
                <td>{{ i+1 }}</td>
                <td>{{ w.name }}</td>
                <td>{{ w.employee_no || '-' }}</td>
                <td>{{ w.output }}</td>
                <td>{{ w.scrap }}</td>
                <td>{{ w.rework }}</td>
                <td :style="{color: w.scrap_rate > 5 ? 'var(--danger)' : ''}">{{ w.scrap_rate }}%</td>
                <td :style="{color: w.rework_rate > 5 ? 'var(--warning)' : ''}">{{ w.rework_rate }}%</td>
                <td>{{ w.work_days }}</td>
                <td>{{ w.daily_avg }}</td>
                <td>{{ w.report_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <p v-else-if="!loading && !workers.length" class="empty"><span class="empty-text">暂无数据</span></p>
  </div>
</template>
<script>
import { useReportWorkers } from '@/composables/reports/useReportWorkers.js'

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    return useReportWorkers(props)
  }
}
</script>
