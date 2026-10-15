<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <h3>👷 员工计件统计</h3>
        <button class="btn btn-success btn-sm" @click="exportCsv" :disabled="!workers.length">📥 CSV</button>
      </div>
    </div>
    <div class="card"><div class="card-header"><h3>📋 工人产量排行</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="workers.length" class="data-table">
        <thead><tr><th style="width:36px"></th><th>#</th><th>姓名</th><th style="text-align:center">出勤天数</th><th style="text-align:center">报工次数</th><th style="text-align:center">产出</th><th style="text-align:center">报废</th></tr></thead>
        <tbody>
          <template v-for="(w,i) in workers" :key="w.id">
            <tr @click="toggleRow(w.id)" style="cursor:pointer" :style="{background: expanded===w.id?'var(--bg-table-header)':''}">
              <td style="text-align:center;font-size:var(--text-xs);color:var(--text-placeholder)">{{ expanded===w.id ? '▼' : '▶' }}</td>
              <td>{{ i+1 }}</td>
              <td style="font-weight:500">{{ w.name }}<span v-if="w.employee_no" style="color:var(--text-placeholder);font-size:var(--text-2xs)"> #{{ w.employee_no }}</span></td>
              <td style="text-align:center">{{ w.work_days || 0 }}</td>
              <td style="text-align:center">{{ w.record_count }}</td>
              <td style="text-align:center;color:var(--success);font-weight:600">{{ w.total_output }}</td>
              <td style="text-align:center;color:var(--danger)">{{ w.total_scrap }}</td>
            </tr>
            <tr v-if="expanded===w.id">
              <td colspan="7" style="padding:0">
                <div style="padding:var(--space-3) var(--space-4);background:var(--bg-hover);border-left:3px solid var(--primary)">
                  <div v-if="loadingDetail===w.id" style="text-align:center;padding:12px;color:var(--text-placeholder)">⏳ 加载中...</div>
                  <table v-else-if="detailRows.length" class="data-table" style="font-size:var(--text-xs);width:100%">
                    <thead><tr><th>产品名称</th><th>型号规格</th><th>工序</th><th style="text-align:center">产量</th><th style="text-align:center">报废</th></tr></thead>
                    <tbody><tr v-for="(r,j) in detailRows" :key="j">
                      <td style="font-weight:500">{{ r.product_name }}</td>
                      <td>{{ r.model }}{{ r.spec ? ' / ' + r.spec : '' }}</td>
                      <td>{{ r.process_name }}</td>
                      <td style="text-align:center;color:var(--success);font-weight:600">{{ r.output }}</td>
                      <td style="text-align:center;color:var(--danger)">{{ r.scrap || 0 }}</td>
                    </tr></tbody>
                  </table>
                  <p v-else style="text-align:center;padding:12px;color:var(--text-placeholder)">该时间段内无报工明细</p>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table><p v-else class="empty"><span class="empty-text">暂无数据（仅统计已审批通过的记录）</span></p></div></div>
    </div>
  </div>
</template>
<script>
import { useWorkerStats } from '@/composables/stats/useWorkerStats.js'

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    return useWorkerStats(props)
  }
}
</script>
