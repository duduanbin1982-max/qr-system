import { computed,onMounted,ref } from 'vue'
import { api } from '@/lib/api.js'
import { auth,can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const PENDING_COMMAND_PREFIX='payroll-adjustments:pending-command:'
const pendingCommandsByStorageKey=new Map()
const memoryOnlyStorageKeys=new Set()

function commandKey(action){return `payroll-adjustment-ui:${action}:${Date.now()}:${Math.random().toString(16).slice(2)}`}

function normalizeReason(value){return String(value??'').trim().replace(/\s+/gu,' ')}

function canonicalAmountCents(value){
  const text=String(value??'').trim()
  const match=/^\+?(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text)
  if(!match)throw new Error('金额格式无效')
  const fraction=match[2]||''
  const exponent=Number(match[3]||0)
  if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>1000)throw new Error('金额格式无效')
  const digits=BigInt(`${match[1]}${fraction}`||'0')
  const centShift=2+exponent-fraction.length
  let cents
  if(centShift>=0)cents=digits*(10n**BigInt(centShift))
  else{
    const divisor=10n**BigInt(-centShift)
    cents=digits/divisor
    if((digits%divisor)*2n>=divisor)cents+=1n
  }
  if(cents<=0n||cents>9000000000000000n)throw new Error('金额必须大于 0 且不能超出范围')
  return cents.toString()
}

function inMemoryPendingCommands(storageKey){
  if(!pendingCommandsByStorageKey.has(storageKey))pendingCommandsByStorageKey.set(storageKey,new Map())
  return pendingCommandsByStorageKey.get(storageKey)
}

function readPendingCommands(storageKey){
  const fallback=inMemoryPendingCommands(storageKey)
  let serialized
  try{serialized=sessionStorage.getItem(storageKey)}catch(_){memoryOnlyStorageKeys.add(storageKey);return fallback}
  if(!serialized){
    if(memoryOnlyStorageKeys.has(storageKey))return fallback
    const empty=new Map()
    pendingCommandsByStorageKey.set(storageKey,empty)
    return empty
  }
  try{
    const entries=JSON.parse(serialized)
    const commands=new Map(Array.isArray(entries)?entries.filter(entry=>Array.isArray(entry)&&typeof entry[0]==='string'&&typeof entry[1]==='string'):[])
    pendingCommandsByStorageKey.set(storageKey,commands)
    memoryOnlyStorageKeys.delete(storageKey)
    return commands
  }catch(_){
    const empty=new Map()
    pendingCommandsByStorageKey.set(storageKey,empty)
    memoryOnlyStorageKeys.delete(storageKey)
    return empty
  }
}

function persistPendingCommands(storageKey,commands){
  try{
    if(commands.size)sessionStorage.setItem(storageKey,JSON.stringify([...commands]))
    else sessionStorage.removeItem(storageKey)
    memoryOnlyStorageKeys.delete(storageKey)
  }catch(_){memoryOnlyStorageKeys.add(storageKey)}
}

function pendingCommandKey(storageKey,action,signature){
  const commands=readPendingCommands(storageKey)
  if(commands.has(signature))return commands.get(signature)
  const key=commandKey(action)
  commands.set(signature,key)
  persistPendingCommands(storageKey,commands)
  return key
}

function clearPendingCommand(storageKey,signature){
  const commands=readPendingCommands(storageKey)
  if(!commands.delete(signature))return
  persistPendingCommands(storageKey,commands)
}

export function usePayrollAdjustments() {
  const now=new Date();
  const storageScope=auth.user?.id||auth.user?.user_id||auth.user?.username||'anonymous'
  const createStorageKey=`${PENDING_COMMAND_PREFIX}${storageScope}:create`
  const reverseStorageKey=`${PENDING_COMMAND_PREFIX}${storageScope}:reverse`

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

  async function createAdjustment(){const reason=normalizeReason(form.value.reason);let amountCents;try{amountCents=canonicalAmountCents(form.value.amount)}catch(_){showToast('请完整填写员工、金额和原因','error');return}if(!form.value.employeeId||!reason){showToast('请完整填写员工、金额和原因','error');return}const payload={employee_id:Number(form.value.employeeId),payroll_month:month.value,adjustment_type:form.value.type,amount:form.value.amount,reason};const signature=JSON.stringify({employee_id:payload.employee_id,payroll_month:payload.payroll_month,adjustment_type:payload.adjustment_type,amount_cents:amountCents,reason});payload.idempotency_key=pendingCommandKey(createStorageKey,'create',signature);working.value=true;try{await api.domains.wages.createPayrollAdjustment(payload);clearPendingCommand(createStorageKey,signature);showToast('调整项已追加');form.value={employeeId:'',type:'bonus',amount:'',reason:''};showForm.value=false;await load()}catch(error){showToast(error.message||'保存失败','error')}finally{working.value=false}}

  async function reverse(item){const reason=normalizeReason(window.prompt(`请输入冲销调整项 #${item.id} 的原因`));if(!reason)return;const payload={reason};const signature=JSON.stringify({adjustment_id:item.id,...payload});payload.idempotency_key=pendingCommandKey(reverseStorageKey,'reverse',signature);working.value=true;try{await api.domains.wages.reversePayrollAdjustment(item.id,payload);clearPendingCommand(reverseStorageKey,signature);showToast('冲销记录已追加');await load()}catch(error){showToast(error.message||'冲销失败','error')}finally{working.value=false}}

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
