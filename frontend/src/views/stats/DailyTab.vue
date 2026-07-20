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
import { ref, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
import { exportCSV } from './shared.js'

export default {
  props: { date: { type: String, default: '' }, productCode: { type: String, default: '' } },
  setup(props) {
    const dailyRecords = ref([])
    const dailySummary = ref([])
    const dailyGroups = ref([])
    const summaryTotals = ref({})
    const workTimeSummary = ref({})
    const isTruncated = ref(false)
    const loading = ref(true)
    const employeeSearch = ref('')
    const typeFilter = ref('')
    const openGroups = ref({})
    const canExport = computed(() => can('stats:view'))

    function quantity(value) {
      const number = Number(value || 0)
      return Number.isFinite(number) ? number : 0
    }

    function rate(part, total) {
      const denominator = quantity(total)
      return denominator ? Math.round(quantity(part) / denominator * 10000) / 100 : 0
    }

    function groupKey(group) {
      return String(group.user_id || group.employee_no || group.worker_name || 'unknown')
    }

    function isGroupOpen(key) {
      return openGroups.value[key] !== false
    }

    function toggleGroup(key) {
      openGroups.value = { ...openGroups.value, [key]: !isGroupOpen(key) }
    }

    function summarizeGroup(group, records) {
      const orderSet = new Set()
      const productSet = new Set()
      const result = { ...group, records, record_count: records.length, total_quantity: 0, normal_quantity: 0, scrap_quantity: 0, rework_quantity: 0 }
      records.forEach(record => {
        const qty = quantity(record.quantity)
        result.total_quantity += qty
        if (record.type === 'scrap') result.scrap_quantity += qty
        else if (record.type === 'rework') result.rework_quantity += qty
        else result.normal_quantity += qty
        if (record.order_id) orderSet.add(record.order_id)
        const productKey = record.product_code || record.product_name || ''
        if (productKey) productSet.add(productKey)
      })
      ;['total_quantity', 'normal_quantity', 'scrap_quantity', 'rework_quantity'].forEach(key => {
        if (Number.isInteger(result[key])) result[key] = Number(result[key])
      })
      result.order_count = orderSet.size
      result.product_count = productSet.size
      result.scrap_rate = rate(result.scrap_quantity, result.total_quantity)
      result.rework_rate = rate(result.rework_quantity, result.total_quantity)
      return result
    }

    const filteredEmployeeGroups = computed(() => {
      const keyword = (employeeSearch.value || '').toLowerCase()
      return dailyGroups.value.map(group => {
        const target = [group.worker_name, group.employee_no, group.group_name, group.department_name, group.position_name].join(' ').toLowerCase()
        if (keyword && !target.includes(keyword)) return null
        const records = (group.records || []).filter(record => !typeFilter.value || record.type === typeFilter.value)
        if (!records.length) return null
        return summarizeGroup(group, records)
      }).filter(Boolean)
    })

    const detailRecordCount = computed(() => filteredEmployeeGroups.value.reduce((sum, group) => sum + group.records.length, 0))

    function isValidDate(str) {
      if (!str) return true
      if (!/^\d{4}-\d{2}-\d{2}$/.test(str)) return false
      const [y, m, d] = str.split('-').map(Number)
      const dt = new Date(y, m - 1, d)
      return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d
    }

    function todayLocal() {
      const d = new Date()
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
    }

    function fallbackGroups(records) {
      const map = new Map()
      records.forEach(record => {
        const key = record.user_id || record.employee_no || record.worker_name || 'unknown'
        if (!map.has(key)) map.set(key, { user_id: record.user_id, worker_name: record.worker_name, employee_no: record.employee_no, group_name: record.group_name, department_name: record.department_name, position_name: record.position_name, records: [] })
        map.get(key).records.push(record)
      })
      return Array.from(map.values()).map(group => summarizeGroup(group, group.records))
    }

    async function loadDaily() {
      const d = props.date || todayLocal()
      if (!isValidDate(d)) {
        showToast('日期格式无效', 'warning')
        loading.value = false
        return
      }
      loading.value = true
      try {
        const params = { date: d, per_page: 5000 }
        if (props.productCode) params.product_code = props.productCode
        const res = await api.domains.stats.dailyStats(params)
        dailyRecords.value = res.records || []
        dailySummary.value = res.summary || []
        dailyGroups.value = (res.employee_groups && res.employee_groups.length) ? res.employee_groups : fallbackGroups(dailyRecords.value)
        summaryTotals.value = res.summary_totals || {}
        workTimeSummary.value = res.work_time_summary || {}
        isTruncated.value = !!res.is_truncated
        const nextOpen = {}
        dailyGroups.value.forEach(group => { nextOpen[groupKey(group)] = openGroups.value[groupKey(group)] !== false })
        openGroups.value = nextOpen
      } catch (e) { showToast(e.message, 'error') } finally { loading.value = false }
    }

    function displayWorkNo(record) {
      if (record.qr_mode === 'serial' && record.serial_no) return record.serial_no
      return record.display_order_no || record.order_no
    }

    function timeOnly(value) {
      return value ? String(value).slice(11, 19) || value : '-'
    }

    function productMeta(record) {
      return [record.product_model, record.product_spec, record.product_category].filter(Boolean).join(' / ') || '-'
    }

    function typeLabel(type) {
      return type === 'scrap' ? '报废' : type === 'rework' ? '返修' : '正常'
    }

    function typeClass(type) {
      return type === 'scrap' ? 'badge-danger' : type === 'rework' ? 'badge-warning' : 'badge-success'
    }

    function qualityText(record) {
      const parts = []
      if (record.quality_result) parts.push(record.quality_result)
      if (record.quality_score) parts.push(String(record.quality_score) + '分')
      return parts.join(' / ')
    }

    function exportSummaryCsv() {
      if (!dailySummary.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['工序','报工次数','产出','报废','返修']]
      dailySummary.value.forEach(s => data.push([s.name, s.record_count, s.total_output, s.total_scrap, s.total_rework]))
      exportCSV(data, '日报表_工序汇总_' + (props.date || ''))
    }

    function exportDetailCsv() {
      if (!detailRecordCount.value) { showToast('没有数据可导出', 'warning'); return }
      const data = [['员工','工号','班组','部门','岗位','时间','订单号/序列号','订单','订单号/序列号','产品编码','产品','型号规格','客户','路线/工序','工序','数量','类型','质检','备注']]
      filteredEmployeeGroups.value.forEach(group => {
        group.records.forEach(r => data.push([group.worker_name, group.employee_no || '', group.group_name || '', group.department_name || '', group.position_name || '', r.created_at, displayWorkNo(r), r.order_no || '', r.serial_no || '', r.product_code || '', r.product_name || '', productMeta(r), r.customer || '', r.route_name || '', r.process_name || '', r.quantity, typeLabel(r.type), qualityText(r), r.remark || '']))
        data.push([group.worker_name + ' 小计', group.employee_no || '', '', '', '', '', '', '', '', '', '', '', '', '', '', group.total_quantity, '正常 ' + group.normal_quantity + ' / 返修 ' + group.rework_quantity + ' / 报废 ' + group.scrap_quantity, '', ''])
      })
      exportCSV(data, '日报表_员工明细_' + (props.date || ''))
    }

    watch(() => [props.date, props.productCode], loadDaily, { immediate: true })
    return {
      dailyRecords, dailySummary, dailyGroups, summaryTotals, workTimeSummary, isTruncated, loading,
      employeeSearch, typeFilter, filteredEmployeeGroups, detailRecordCount, canExport,
      loadDaily, displayWorkNo, exportSummaryCsv, exportDetailCsv, groupKey, isGroupOpen,
      toggleGroup, timeOnly, productMeta, typeLabel, typeClass, qualityText,
    }
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
