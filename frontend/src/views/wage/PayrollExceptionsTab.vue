<template>
  <div>
    <div class="exception-toolbar">
      <div><h3>工资异常队列</h3><p>异常工价和返工倍率必须由制单人提出、另一名审批人确认。</p></div>
      <div class="exception-actions">
        <input v-model="month" type="month" class="form-input" @change="load">
        <select v-model="status" class="form-input" @change="load">
          <option value="">全部状态</option><option value="pending">待处理</option>
          <option value="proposed">待审批</option><option value="approved">已批准</option>
          <option value="rejected">已驳回</option>
        </select>
        <button class="btn-default btn-sm" @click="load">刷新</button>
      </div>
    </div>
    <div class="card exception-table-wrap">
      <div v-if="loading" class="exception-empty">加载中...</div>
      <div v-else-if="!items.length" class="exception-empty">当前筛选条件下没有工资异常</div>
      <table v-else class="data-table exception-table">
        <thead><tr><th>批次</th><th>员工</th><th>报工</th><th>异常</th><th>核定工价</th><th>返工倍率</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <template v-for="item in items" :key="item.id">
            <tr>
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
              <td colspan="8">
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
  loading,
  working,
  editingId,
  form,
  canPrepare,
  canApprove,
  parsed,
  labels,
  statuses,
  snapshot,
  exceptionLabel,
  statusLabel,
  price,
  rate,
  load,
  edit,
  propose,
  approve
} = usePayrollExceptions()
</script>

<style scoped>
.exception-toolbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.exception-toolbar h3{margin:0;font-size:18px}.exception-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.exception-actions{display:flex;gap:8px}.exception-actions .form-input{width:145px}.exception-table-wrap{padding:0;overflow-x:auto;border-radius:8px}.exception-table{width:100%;min-width:920px}.exception-table small{display:block;margin-top:2px;color:var(--text-placeholder)}.exception-empty{text-align:center;padding:48px;color:var(--text-placeholder)}.exception-status{display:inline-block;padding:2px 7px;border-radius:4px;background:var(--bg-secondary);font-size:12px}.status-proposed{color:var(--primary);background:var(--primary-light)}.status-approved{color:var(--success);background:var(--success-light)}.status-rejected{color:var(--danger);background:var(--danger-light)}.proposal-row td{background:var(--bg-secondary)}.proposal-form{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.proposal-form label{display:flex;flex-direction:column;gap:4px;color:var(--text-placeholder);font-size:12px}.proposal-form .form-input{width:150px}.proposal-form .reason{flex:1;min-width:220px}.proposal-form .reason .form-input{width:100%}@media(max-width:760px){.exception-toolbar{flex-direction:column}.exception-actions{width:100%;flex-wrap:wrap}}
</style>
