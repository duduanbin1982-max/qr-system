<template>
  <div>
    <div class="adjustment-toolbar">
      <div><h3>工资调整项</h3><p>调整项不可修改或删除；录入错误时创建等额冲销记录。</p></div>
      <div class="adjustment-actions"><input v-model="month" type="month" class="form-input" @change="load"><button class="btn-default btn-sm" @click="load">刷新</button><button v-if="canPrepare" class="btn-primary btn-sm" @click="showForm=!showForm">新增调整</button></div>
    </div>
    <div v-if="showForm" class="adjustment-form">
      <label>员工<select v-model="form.employeeId" class="form-input"><option value="">请选择</option><option v-for="employee in employees" :key="employee.id" :value="employee.id">{{ employee.name }}{{ employee.employee_no ? ` (${employee.employee_no})` : '' }}</option></select></label>
      <label>类型<select v-model="form.type" class="form-input"><option value="bonus">奖金</option><option value="allowance">补贴</option><option value="deduction">扣款</option></select></label>
      <label>金额（元）<input v-model="form.amount" type="number" min="0.01" step="0.01" class="form-input"></label>
      <label class="reason">原因<input v-model="form.reason" class="form-input" placeholder="填写调整依据"></label>
      <button class="btn-primary btn-sm" :disabled="working" @click="createAdjustment">保存</button><button class="btn-default btn-sm" @click="showForm=false">取消</button>
    </div>
    <div class="adjustment-summary"><span>奖金 {{ money(totals.bonus) }}</span><span>补贴 {{ money(totals.allowance) }}</span><span>扣款 {{ money(totals.deduction) }}</span><strong>净调整 {{ money(totals.net) }}</strong></div>
    <div class="card adjustment-table-wrap">
      <div v-if="loading" class="adjustment-empty">加载中...</div><div v-else-if="!items.length" class="adjustment-empty">暂无调整记录</div>
      <table v-else class="data-table adjustment-table"><thead><tr><th>员工</th><th>类型</th><th class="text-right">金额</th><th>原因</th><th>制单人 / 时间</th><th>关联</th><th>操作</th></tr></thead>
        <tbody><tr v-for="item in items" :key="item.id"><td>{{ item.employee_name_snapshot }}<small>{{ item.employee_no_snapshot||'' }}</small></td><td>{{ typeLabel(item.adjustment_type) }}</td><td class="text-right" :class="item.adjustment_type==='deduction'?'text-danger':'text-success'">{{ signedMoney(item) }}</td><td>{{ item.reason }}</td><td>{{ item.created_by_name||'-' }}<small>{{ item.created_at }}</small></td><td>{{ item.reversal_of_id ? `冲销 #${item.reversal_of_id}` : item.legacy_wage_adjustment_id ? 'Legacy 导入' : '-' }}</td><td><button v-if="canPrepare && !item.reversal_of_id && !reversedIds.has(item.id)" class="btn-default btn-sm" :disabled="working" @click="reverse(item)">冲销</button><span v-else-if="reversedIds.has(item.id)" class="text-placeholder">已冲销</span></td></tr></tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { usePayrollAdjustments } from '@/composables/wage/usePayrollAdjustments.js'

const {
  now,
  month,
  items,
  employees,
  loading,
  working,
  showForm,
  form,
  canPrepare,
  reversedIds,
  totals,
  money,
  signedMoney,
  typeLabel,
  load,
  loadEmployees,
  createAdjustment,
  reverse
} = usePayrollAdjustments()
</script>

<style scoped>
.adjustment-toolbar{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:12px}.adjustment-toolbar h3{margin:0;font-size:18px}.adjustment-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.adjustment-actions{display:flex;gap:8px}.adjustment-form{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;padding:12px;background:var(--bg-secondary);border-top:1px solid var(--border-light);border-bottom:1px solid var(--border-light);margin-bottom:12px}.adjustment-form label{display:flex;flex-direction:column;gap:4px;color:var(--text-placeholder);font-size:12px}.adjustment-form label:first-child{min-width:190px}.adjustment-form .reason{flex:1;min-width:220px}.adjustment-summary{display:flex;justify-content:flex-end;gap:20px;padding:10px 0;font-size:13px}.adjustment-table-wrap{padding:0;overflow-x:auto;border-radius:8px}.adjustment-table{width:100%;min-width:900px}.adjustment-table small{display:block;color:var(--text-placeholder);margin-top:2px}.adjustment-empty{text-align:center;padding:48px;color:var(--text-placeholder)}.text-right{text-align:right}.text-placeholder{color:var(--text-placeholder);font-size:12px}@media(max-width:760px){.adjustment-toolbar{flex-direction:column}.adjustment-form label,.adjustment-form label:first-child,.adjustment-form .reason{width:100%;min-width:0}.adjustment-summary{justify-content:flex-start;flex-wrap:wrap}}
</style>
