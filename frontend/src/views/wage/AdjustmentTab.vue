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
import { computed,onMounted,ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'
const now=new Date();const month=ref(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`)
const items=ref([]),employees=ref([]),loading=ref(false),working=ref(false),showForm=ref(false)
const form=ref({employeeId:'',type:'bonus',amount:'',reason:''})
const canPrepare=computed(()=>can('wages:prepare'))
const reversedIds=computed(()=>new Set(items.value.filter(item=>item.reversal_of_id).map(item=>item.reversal_of_id)))
const totals=computed(()=>items.value.reduce((result,item)=>{const sign=item.reversal_of_id?-1:1;result[item.adjustment_type]+=Number(item.amount_cents||0)*sign;result.net=(result.bonus+result.allowance-result.deduction);return result},{bonus:0,allowance:0,deduction:0,net:0}))
function money(cents){const value=Number(cents||0);return `${value<0?'-':''}¥${(Math.abs(value)/100).toFixed(2)}`}
function signedMoney(item){const sign=item.reversal_of_id?-1:1;return money(Number(item.amount_cents||0)*sign)}
function typeLabel(value){return {bonus:'奖金',allowance:'补贴',deduction:'扣款'}[value]||value}
async function load(){loading.value=true;try{const data=await api.domains.wages.listPayrollAdjustments({payroll_month:month.value});items.value=data.adjustments||[]}catch(error){showToast(error.message||'调整项加载失败','error')}finally{loading.value=false}}
async function loadEmployees(){if(!canPrepare.value)return;try{const data=await api.domains.users.listUsers({limit:500});employees.value=(data.users||[]).filter(item=>item.status!=='disabled')}catch(error){showToast(error.message||'员工加载失败','error')}}
async function createAdjustment(){if(!form.value.employeeId||Number(form.value.amount)<=0||!form.value.reason.trim()){showToast('请完整填写员工、金额和原因','error');return}working.value=true;try{await api.domains.wages.createPayrollAdjustment({employee_id:Number(form.value.employeeId),payroll_month:month.value,adjustment_type:form.value.type,amount:form.value.amount,reason:form.value.reason.trim()});showToast('调整项已追加');form.value={employeeId:'',type:'bonus',amount:'',reason:''};showForm.value=false;await load()}catch(error){showToast(error.message||'保存失败','error')}finally{working.value=false}}
async function reverse(item){const reason=window.prompt(`请输入冲销调整项 #${item.id} 的原因`);if(!reason?.trim())return;working.value=true;try{await api.domains.wages.reversePayrollAdjustment(item.id,reason.trim());showToast('冲销记录已追加');await load()}catch(error){showToast(error.message||'冲销失败','error')}finally{working.value=false}}
onMounted(()=>{load();loadEmployees()})
</script>

<style scoped>
.adjustment-toolbar{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:12px}.adjustment-toolbar h3{margin:0;font-size:18px}.adjustment-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.adjustment-actions{display:flex;gap:8px}.adjustment-form{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;padding:12px;background:var(--bg-secondary);border-top:1px solid var(--border-light);border-bottom:1px solid var(--border-light);margin-bottom:12px}.adjustment-form label{display:flex;flex-direction:column;gap:4px;color:var(--text-placeholder);font-size:12px}.adjustment-form label:first-child{min-width:190px}.adjustment-form .reason{flex:1;min-width:220px}.adjustment-summary{display:flex;justify-content:flex-end;gap:20px;padding:10px 0;font-size:13px}.adjustment-table-wrap{padding:0;overflow-x:auto;border-radius:8px}.adjustment-table{width:100%;min-width:900px}.adjustment-table small{display:block;color:var(--text-placeholder);margin-top:2px}.adjustment-empty{text-align:center;padding:48px;color:var(--text-placeholder)}.text-right{text-align:right}.text-placeholder{color:var(--text-placeholder);font-size:12px}@media(max-width:760px){.adjustment-toolbar{flex-direction:column}.adjustment-form label,.adjustment-form label:first-child,.adjustment-form .reason{width:100%;min-width:0}.adjustment-summary{justify-content:flex-start;flex-wrap:wrap}}
</style>
