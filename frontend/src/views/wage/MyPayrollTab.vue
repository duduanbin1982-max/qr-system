<template>
  <div>
    <div class="my-payroll-toolbar">
      <div><h3>我的工资</h3><p>这里只显示已确认且未被修订版替代的正式工资。</p></div>
      <div><input v-model="month" type="month" class="form-input" @change="load"><button class="btn-default btn-sm" @click="load">查询</button></div>
    </div>
    <div v-if="loading" class="my-payroll-empty">加载中...</div>
    <div v-else-if="!lines.length" class="my-payroll-empty">当前月份没有已确认工资</div>
    <div v-else class="my-payroll-list">
      <div v-for="line in lines" :key="line.id" class="my-payroll-sheet">
        <div class="sheet-head"><div><strong>{{ line.payroll_month }} / V{{ line.version }}</strong><span>已确认</span></div><strong>{{ money(line.payable_wage_cents) }}</strong></div>
        <div class="sheet-grid">
          <div><span>正常件数</span><strong>{{ line.normal_quantity }}</strong></div><div><span>返工件数</span><strong>{{ line.rework_quantity }}</strong></div>
          <div><span>正常工资</span><strong>{{ money(line.normal_wage_cents) }}</strong></div><div><span>返工工资</span><strong>{{ money(line.rework_wage_cents) }}</strong></div>
          <div><span>奖金及补贴</span><strong>{{ money(line.bonus_cents + line.allowance_cents) }}</strong></div><div><span>扣款</span><strong>{{ money(line.deduction_cents) }}</strong></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
const now=new Date()
const month=ref(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`)
const lines=ref([])
const loading=ref(false)
function money(cents){return `¥${(Number(cents||0)/100).toFixed(2)}`}
async function load(){loading.value=true;try{const data=await api.domains.wages.getMyPayroll(month.value);lines.value=data.lines||[]}catch(error){showToast(error.message||'本人工资加载失败','error')}finally{loading.value=false}}
onMounted(load)
</script>

<style scoped>
.my-payroll-toolbar{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:12px}.my-payroll-toolbar h3{margin:0;font-size:18px}.my-payroll-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.my-payroll-toolbar>div:last-child{display:flex;gap:8px}.my-payroll-empty{text-align:center;padding:56px;color:var(--text-placeholder)}.my-payroll-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}.my-payroll-sheet{border:1px solid var(--border-light);border-radius:8px;background:white}.sheet-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border-light)}.sheet-head div{display:flex;align-items:center;gap:8px}.sheet-head span{padding:2px 6px;border-radius:4px;background:var(--success-light);color:var(--success);font-size:12px}.sheet-head>strong{font-size:20px}.sheet-grid{display:grid;grid-template-columns:repeat(2,1fr)}.sheet-grid div{padding:12px 16px;border-right:1px solid var(--border-light);border-bottom:1px solid var(--border-light)}.sheet-grid div:nth-child(2n){border-right:0}.sheet-grid div:nth-last-child(-n+2){border-bottom:0}.sheet-grid span{display:block;color:var(--text-placeholder);font-size:12px}.sheet-grid strong{display:block;margin-top:3px}@media(max-width:650px){.my-payroll-toolbar{flex-direction:column}.my-payroll-list{grid-template-columns:1fr}}
</style>
