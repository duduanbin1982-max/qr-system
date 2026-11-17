<template>
  <div>
    <div class="exception-toolbar">
      <div><h3>工资异常中心</h3><p>阻断异常需修正报工来源并重算；复核项须保留审批人的书面结论。</p></div>
      <div class="exception-actions">
        <input v-model="month" type="month" class="form-input" @change="load">
        <select v-model="status" class="form-input" aria-label="工价异常状态" @change="load">
          <option value="">全部状态</option><option value="pending">待处理</option>
          <option value="proposed">待审批</option><option value="approved">已批准</option>
          <option value="rejected">已驳回</option>
        </select>
        <select v-model="auditStatus" class="form-input" aria-label="审计异常状态" :disabled="includeAuditHistory" @change="load">
          <option value="open">待处理审计</option><option value="resolved">已复核审计</option>
          <option value="">全部当前审计</option>
        </select>
        <label class="audit-history-toggle">
          <input v-model="includeAuditHistory" type="checkbox" @change="load">
          查看重算历史
        </label>
        <button class="btn-default btn-sm" @click="load">刷新</button>
      </div>
    </div>
    <div v-if="canApprove" class="bulk-exception-toolbar">
      <label><input type="checkbox" :checked="allSelectableSelected" @change="toggleAllSelected"> 全选待审批</label>
      <span>待审批 {{ selectableItems.length }} 条，已选 {{ selectedIds.length }} 条</span>
      <button class="btn-primary btn-sm" :disabled="working || !selectedIds.length" @click="bulkApprove">集中批准<span v-if="selectedIds.length">（{{ selectedIds.length }}）</span></button>
      <small v-if="!selectableItems.length" class="bulk-empty-note">当前没有待审批异常</small>
    </div>
    <div v-if="bulkResult" class="bulk-result-panel" role="status">
      <strong>本次处理：成功 {{ bulkResult.success }} 条，失败 {{ bulkResult.failed }} 条</strong>
      <ul v-if="bulkResult.failed">
        <li v-for="item in bulkResult.items.filter(row => !row.ok)" :key="item.id">{{ item.label }} #{{ item.id }}：{{ item.reason }}</li>
      </ul>
    </div>
    <section class="audit-findings-section" aria-labelledby="audit-findings-title">
      <div class="audit-section-heading">
        <h4 id="audit-findings-title">计算审计异常</h4>
        <span>{{ auditFindings.length }} 条</span>
      </div>
      <div v-if="loading" class="exception-empty">加载审计异常...</div>
      <div v-else-if="!auditFindings.length" class="exception-empty">当前计算版本没有匹配的审计规则</div>
      <div v-else class="audit-findings-table-wrap">
        <table class="data-table audit-findings-table">
          <thead><tr><th>批次</th><th>风险</th><th>对象</th><th>规则依据</th><th>状态</th><th>复核</th></tr></thead>
          <tbody>
            <tr v-for="finding in auditFindings" :key="finding.id">
              <td>{{ finding.payroll_month }} / V{{ finding.batch_version }}<small>计算版本 {{ finding.calculation_version }}</small></td>
              <td>
                <strong>{{ findingLabel(finding.finding_type) }}</strong>
                <small :class="finding.severity==='blocking'?'severity-blocking':'severity-review'">
                  {{ finding.severity==='blocking'?'阻断':'人工复核' }} · {{ finding.rule_version }}
                </small>
              </td>
              <td>{{ findingSubject(finding) }}</td>
              <td class="finding-basis">
                <p>{{ findingSnapshot(finding).summary || '规则命中' }}</p>
                <details>
                  <summary>查看计算依据</summary>
                  <ul><li v-for="(evidence, index) in findingEvidence(finding)" :key="index">{{ evidence }}</li></ul>
                </details>
              </td>
              <td><span class="exception-status" :class="'status-'+finding.status">{{ findingStatusLabel(finding.status) }}</span></td>
              <td>
                <div v-if="finding.status==='open' && finding.severity==='review' && canApprove" class="finding-review">
                  <select v-model="auditResolutionCodes[finding.id]" class="form-input" :aria-label="'复核结论 '+finding.id">
                    <option value="" disabled>选择复核结论</option>
                    <option v-for="option in findingResolutionOptions(finding)" :key="option.code" :value="option.code">{{ option.label }}</option>
                  </select>
                  <input v-model="auditResolutions[finding.id]" class="form-input" :aria-label="'复核原因 '+finding.id" placeholder="填写复核依据">
                  <button class="btn-primary btn-sm" :disabled="working" @click="resolveAuditFinding(finding)">记录复核</button>
                </div>
                <small v-else-if="finding.status==='open' && finding.severity==='blocking'" class="blocking-guidance">修正来源记录后重算</small>
                <small v-else>{{ finding.resolved_by_name ? '由 ' + finding.resolved_by_name + ' 处理：' : '' }}{{ finding.resolution_reason || '-' }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <div class="card exception-table-wrap">
      <div v-if="loading" class="exception-empty">加载中...</div>
      <div v-else-if="!items.length" class="exception-empty">当前筛选条件下没有待处理工价异常</div>
      <table v-else class="data-table exception-table">
          <thead><tr><th>选择</th><th>批次</th><th>员工</th><th>报工</th><th>异常</th><th>核定工价</th><th>返工倍率</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <template v-for="item in items" :key="item.id">
            <tr>
              <td><input v-if="canApprove && item.status==='proposed'" type="checkbox" :checked="selectedIds.includes(item.id)" :aria-label="`选择异常 ${item.id}`" @change="toggleSelected(item.id)"></td>
              <td>{{ item.payroll_month }} / V{{ item.version }}</td>
              <td>{{ item.employee_name || snapshot(item).employee_name || '-' }}<small>{{ item.employee_no || '' }}</small></td>
              <td>{{ snapshot(item).order_no || '-' }}<small>{{ snapshot(item).process_name || '-' }} · {{ snapshot(item).quantity || 0 }} 件</small></td>
              <td>{{ exceptionLabel(item.exception_type) }}</td>
              <td>{{ item.proposed_price_micros == null ? '-' : price(item.proposed_price_micros) }}</td>
              <td>{{ item.proposed_rework_rate_basis_points == null ? '-' : rate(item.proposed_rework_rate_basis_points) }}</td>
              <td><span class="exception-status" :class="'status-'+item.status">{{ statusLabel(item.status) }}</span></td>
              <td>
                <button v-if="canPrepare && ['pending','rejected'].includes(item.status)" class="btn-default btn-sm" @click="edit(item)">提出方案</button>
                <button v-if="canApprove && item.status==='proposed'" class="btn-primary btn-sm" :disabled="working" @click="approve(item)">批准</button>
              </td>
            </tr>
            <tr v-if="editingId===item.id" class="proposal-row">
              <td colspan="9">
                <div class="proposal-form">
                  <label>核定工价（元）<input v-model="form.unitPrice" type="number" min="0.0001" step="0.0001" class="form-input" :placeholder="item.exception_type==='missing_rework_rate'?'可沿用已有工价':'必填'"></label>
                  <label>返工倍率（%）<input v-model="form.reworkPercent" type="number" min="0" max="100" step="0.01" class="form-input" :disabled="snapshot(item).type!=='rework'"></label>
                  <label class="reason">核定原因<input v-model="form.reason" class="form-input" placeholder="填写核定依据和凭证编号"></label>
                  <button class="btn-primary btn-sm" :disabled="working" @click="propose(item)">提交审批</button>
                  <button class="btn-default btn-sm" @click="editingId=null">取消</button>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { usePayrollExceptions } from '@/composables/wage/usePayrollExceptions.js'

const {
  now,
  month,
  status,
  items,
  auditFindings,
  auditStatus,
  includeAuditHistory,
  auditResolutions,
  auditResolutionCodes,
  loading,
  working,
  editingId,
  form,
  selectedIds,
  selectableItems,
  allSelectableSelected,
  bulkResult,
  canPrepare,
  canApprove,
  parsed,
  labels,
  statuses,
  findingLabels,
  findingStatuses,
  snapshot,
  exceptionLabel,
  statusLabel,
  findingLabel,
  findingStatusLabel,
  findingResolutionOptions,
  findingSnapshot,
  findingSubject,
  findingEvidence,
  price,
  rate,
  load,
  edit,
  propose,
  approve,
  toggleSelected,
  toggleAllSelected,
  bulkApprove,
  resolveAuditFinding
} = usePayrollExceptions()
</script>

<style scoped>
.exception-toolbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.exception-toolbar h3{margin:0;font-size:18px}.exception-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.exception-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.exception-actions .form-input{width:145px}.audit-history-toggle{display:flex;align-items:center;gap:6px;white-space:nowrap;color:var(--text-secondary);font-size:12px}.audit-findings-section{margin:0 0 16px}.audit-section-heading{display:flex;align-items:center;justify-content:space-between;margin:0 0 8px}.audit-section-heading h4{margin:0;font-size:15px}.audit-section-heading span{color:var(--text-placeholder);font-size:12px}.audit-findings-table-wrap{overflow-x:auto;border:1px solid var(--border-color);border-radius:6px}.audit-findings-table{width:100%;min-width:1050px}.audit-findings-table small{display:block;margin-top:3px;color:var(--text-placeholder)}.finding-basis{max-width:420px;white-space:normal}.finding-basis p{margin:0}.finding-basis details{margin-top:5px;color:var(--text-secondary);font-size:12px}.finding-basis summary{cursor:pointer;color:var(--primary)}.finding-basis ul{margin:5px 0 0;padding-left:18px}.finding-review{display:grid;grid-template-columns:minmax(140px,1fr) auto;gap:6px;min-width:250px}.severity-blocking,.blocking-guidance{color:var(--danger)!important}.severity-review{color:var(--warning)!important}.exception-table-wrap{padding:0;overflow-x:auto;border-radius:8px}.exception-table{width:100%;min-width:920px}.exception-table small{display:block;margin-top:2px;color:var(--text-placeholder)}.exception-empty{text-align:center;padding:32px;color:var(--text-placeholder)}.exception-status{display:inline-block;padding:2px 7px;border-radius:4px;background:var(--bg-secondary);font-size:12px}.status-proposed{color:var(--primary);background:var(--primary-light)}.status-approved,.status-resolved{color:var(--success);background:var(--success-light)}.status-rejected{color:var(--danger);background:var(--danger-light)}.proposal-row td{background:var(--bg-secondary)}.proposal-form{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.proposal-form label{display:flex;flex-direction:column;gap:4px;color:var(--text-placeholder);font-size:12px}.proposal-form .form-input{width:150px}.proposal-form .reason{flex:1;min-width:220px}.proposal-form .reason .form-input{width:100%}@media(max-width:760px){.exception-toolbar{flex-direction:column}.exception-actions{width:100%;flex-wrap:wrap}.exception-actions .form-input{width:auto;min-width:130px}}
.finding-review{grid-template-columns:minmax(140px,1fr) minmax(160px,1fr) auto;min-width:390px}
.bulk-exception-toolbar{display:flex;align-items:center;gap:12px;padding:10px 12px;margin-bottom:10px;border:1px solid var(--border-light);background:var(--bg-secondary);font-size:12px}.bulk-result-panel{padding:10px 12px;margin-bottom:10px;border-left:3px solid var(--primary);background:var(--primary-light);font-size:12px}.bulk-result-panel ul{margin:6px 0 0;padding-left:18px}
.bulk-empty-note{color:var(--text-placeholder)}
</style>
