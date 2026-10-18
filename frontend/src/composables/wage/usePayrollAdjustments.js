import { computed,onMounted,ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function usePayrollAdjustments() {
  const now=new Date();

  const month=ref(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`)

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

  return {
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
  }
}
