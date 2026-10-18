<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header daily-header">
        <h3>生产日报表</h3>
        <div v-if="canExport" class="daily-actions">
          <button class="btn btn-outline btn-sm" @click="exportSummaryCsv" :disabled="!dailySummary.length">导出汇总</button>
          <button class="btn btn-outline btn-sm" @click="exportDetailCsv" :disabled="!detailRecordCount">导出明细</button>
        </div>
      </div>
    </div>

    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>

    <div v-else>
      <div class="daily-total-grid" v-if="summaryTotals.record_count || dailyRecords.length || workTimeSummary.record_count">
        <div class="daily-total-card"><span>报工记录</span><strong>{{ summaryTotals.record_count || dailyRecords.length }}</strong></div>
        <div class="daily-total-card"><span>报工数量</span><strong>{{ summaryTotals.total_quantity || 0 }}</strong></div>
        <div class="daily-total-card"><span>参与员工</span><strong>{{ summaryTotals.worker_count || dailyGroups.length }}</strong></div>
        <div class="daily-total-card"><span>涉及订单</span><strong>{{ summaryTotals.order_count || 0 }}</strong></div>
        <div class="daily-total-card"><span>涉及产品</span><strong>{{ summaryTotals.product_count || 0 }}</strong></div>
        <div class="daily-total-card success"><span>正常</span><strong>{{ summaryTotals.normal_quantity || 0 }}</strong></div>
        <div class="daily-total-card warning"><span>返修</span><strong>{{ summaryTotals.rework_quantity || 0 }}</strong><small>{{ summaryTotals.rework_rate || 0 }}%</small></div>
        <div class="daily-total-card danger"><span>报废</span><strong>{{ summaryTotals.scrap_quantity || 0 }}</strong><small>{{ summaryTotals.scrap_rate || 0 }}%</small></div>
      </div>

      <div v-if="workTimeSummary.record_count" class="daily-work-time-grid">
        <div class="daily-total-card"><span>工时流水</span><strong>{{ workTimeSummary.record_count }}</strong></div>
        <div class="daily-total-card"><span>有效工时(h)</span><strong>{{ workTimeSummary.effective_hours || 0 }}</strong></div>
        <div class="daily-total-card"><span>工时效率</span><strong>{{ workTimeSummary.efficiency || 0 }}%</strong></div>
        <div class="daily-total-card warning"><span>异常工时</span><strong>{{ workTimeSummary.abnormal_count || 0 }}</strong></div>
        <div class="daily-total-card warning"><span>缺标准</span><strong>{{ workTimeSummary.missing_standard_count || 0 }}</strong></div>
      </div>

      <div v-if="isTruncated" class="daily-warning">数据已截断，请缩小筛选条件</div>

      <div class="card" style="margin-bottom:var(--space-4)" v-if="dailySummary.length">
        <div class="card-header"><h3>工序汇总</h3></div>
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
        <div class="card-header daily-detail-header">
          <h3>按员工分组的日报工明细 ({{ detailRecordCount }})</h3>
          <div class="daily-detail-filters">
            <input class="form-input" v-model.trim="employeeSearch" placeholder="搜索员工/工号/班组" style="width:180px">
            <select class="form-input" v-model="typeFilter" style="width:120px">
              <option value="">全部类型</option>
              <option value="normal">正常</option>
              <option value="rework">返修</option>
              <option value="scrap">报废</option>
            </select>
          </div>
        </div>
        <div class="card-body">
          <div v-if="filteredEmployeeGroups.length" class="employee-report-list">
            <div v-for="group in filteredEmployeeGroups" :key="groupKey(group)" class="employee-report-group">
              <div class="employee-group-head" @click="toggleGroup(groupKey(group))">
                <div>
                  <strong>{{ group.worker_name || '-' }}</strong>
                  <span v-if="group.employee_no" class="muted">#{{ group.employee_no }}</span>
                  <span v-if="group.group_name" class="badge badge-secondary">{{ group.group_name }}</span>
                  <span v-if="group.department_name" class="muted">{{ group.department_name }}</span>
                  <span v-if="group.position_name" class="muted">{{ group.position_name }}</span>
                </div>
                <div class="employee-group-stats">
                  <span>次数 {{ group.record_count }}</span>
                  <span>数量 {{ group.total_quantity }}</span>
                  <span class="ok">正常 {{ group.normal_quantity }}</span>
                  <span class="warn">返修 {{ group.rework_quantity }} / {{ group.rework_rate }}%</span>
                  <span class="bad">报废 {{ group.scrap_quantity }} / {{ group.scrap_rate }}%</span>
                  <span>订单 {{ group.order_count }}</span>
                  <span>产品 {{ group.product_count }}</span>
                  <button class="btn btn-sm btn-default" @click.stop="toggleGroup(groupKey(group))">{{ isGroupOpen(groupKey(group)) ? '收起' : '展开' }}</button>
                </div>
              </div>
              <div v-if="isGroupOpen(groupKey(group))" class="table-wrap">
                <table class="data-table daily-detail-table">
                  <thead>
                    <tr>
                      <th>时间</th><th>订单号/序列号</th><th>产品编码</th><th>产品信息</th><th>客户</th><th>路线/工序</th><th style="text-align:center">数量</th><th>类型</th><th>质检</th><th>备注</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="r in group.records" :key="r.id">
                      <td style="white-space:nowrap">{{ timeOnly(r.created_at) }}</td>
                      <td><code>{{ displayWorkNo(r) }}</code></td>
                      <td><code>{{ r.product_code || '-' }}</code></td>
                      <td>
                        <div>{{ r.product_name || '-' }}</div>
                        <div class="muted">{{ productMeta(r) }}</div>
                      </td>
                      <td>{{ r.customer || '-' }}</td>
                      <td>
                        <div>{{ r.process_name || '-' }}</div>
                        <div class="muted">{{ r.route_name || '-' }}</div>
                      </td>
                      <td style="text-align:center;font-weight:600">{{ r.quantity }}</td>
                      <td><span class="badge" :class="typeClass(r.type)">{{ typeLabel(r.type) }}</span></td>
                      <td>
                        <span v-if="r.quality_result || r.quality_score" class="muted">{{ qualityText(r) }}</span>
                        <span v-else class="muted">-</span>
                      </td>
                      <td class="muted">{{ r.remark || '-' }}</td>
                    </tr>
                    <tr class="employee-subtotal-row">
                      <td colspan="6">{{ group.worker_name }} 小计</td>
                      <td style="text-align:center">{{ group.total_quantity }}</td>
                      <td colspan="3">正常 {{ group.normal_quantity }} / 返修 {{ group.rework_quantity }} / 报废 {{ group.scrap_quantity }} / 订单 {{ group.order_count }} / 产品 {{ group.product_count }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <p v-else class="empty">该日期无报工记录（仅显示已审批通过的记录）</p>
        </div>
      </div>
    </div>
  </div>
</template>
<script>
import { useDailyStats } from '@/composables/stats/useDailyStats.js'

export default {
  props: { date: { type: String, default: '' }, productCode: { type: String, default: '' } },
  setup(props) {
    return useDailyStats(props)
  }
}
</script>
<style scoped>
.daily-header, .daily-detail-header { display:flex; align-items:center; justify-content:space-between; gap:var(--space-3); flex-wrap:wrap; }
.daily-actions, .daily-detail-filters { display:flex; gap:var(--space-2); align-items:center; flex-wrap:wrap; }
.daily-total-grid, .daily-work-time-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:var(--space-3); margin-bottom:var(--space-4); }
.daily-total-card { background:var(--bg-surface); border:1px solid var(--border-light); border-radius:var(--radius-lg); padding:var(--space-3); box-shadow:var(--shadow-sm); }
.daily-total-card span { display:block; color:var(--text-placeholder); font-size:var(--text-xs); margin-bottom:4px; }
.daily-total-card strong { font-size:22px; color:var(--text-primary); }
.daily-total-card small { margin-left:6px; color:var(--text-placeholder); }
.daily-total-card.success strong { color:var(--success); }
.daily-total-card.warning strong { color:var(--warning); }
.daily-total-card.danger strong { color:var(--danger); }
.daily-warning { margin-bottom:var(--space-4); padding:var(--space-3); border-radius:var(--radius-md); background:var(--warning-light); color:var(--warning); }
.employee-report-list { display:flex; flex-direction:column; gap:var(--space-3); }
.employee-report-group { border:1px solid var(--border-light); border-radius:var(--radius-lg); overflow:hidden; background:var(--bg-surface); }
.employee-group-head { display:flex; justify-content:space-between; gap:var(--space-3); align-items:center; padding:var(--space-3); background:var(--bg-hover); cursor:pointer; flex-wrap:wrap; }
.employee-group-stats { display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:var(--text-xs); color:var(--text-secondary); }
.employee-group-stats .ok { color:var(--success); }
.employee-group-stats .warn { color:var(--warning); }
.employee-group-stats .bad { color:var(--danger); }
.daily-detail-table { font-size:var(--text-xs); }
.daily-detail-table td, .daily-detail-table th { vertical-align:top; }
.employee-subtotal-row { background:var(--bg-hover); font-weight:600; }
.muted { color:var(--text-placeholder); font-size:var(--text-xs-alt); margin-left:4px; }
@media (max-width: 768px) {
  .daily-total-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .employee-group-head { align-items:flex-start; }
  .daily-detail-filters input, .daily-detail-filters select { width:100% !important; }
}
</style>
