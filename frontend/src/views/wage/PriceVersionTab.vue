<template>
  <div>
    <div class="price-toolbar">
      <div><h3>工价版本</h3><p>已批准工价不可修改；调价必须新增草稿并由另一名用户批准。</p></div>
      <div class="price-actions">
        <select v-model="status" class="form-input" @change="load"><option value="">全部状态</option><option value="draft">草稿</option><option value="approved">已批准</option><option value="retired">已结束</option></select>
        <button class="btn-default btn-sm" @click="load">刷新</button>
        <button v-if="canPrepare" class="btn-primary btn-sm" @click="showForm=!showForm">新增版本</button>
      </div>
    </div>
    <div v-if="showForm" class="price-form">
      <label>路线 / 工序<select v-model="form.reference" class="form-input"><option value="">请选择</option><option v-for="item in references" :key="`${item.route_id}:${item.process_id}`" :value="`${item.route_id}:${item.process_id}`">{{ item.route_name }} / {{ item.process_name }}</option></select></label>
      <label>正常工价（元）<input v-model="form.unitPrice" type="number" min="0.0001" step="0.0001" class="form-input"></label>
      <label>生效时间<input v-model="form.validFrom" type="datetime-local" class="form-input"></label>
      <label class="rate-toggle"><input v-model="form.reworkConfigured" type="checkbox"> 配置返工倍率</label>
      <label v-if="form.reworkConfigured">返工倍率（%）<input v-model="form.reworkPercent" type="number" min="0" max="100" step="0.01" class="form-input"></label>
      <label class="remark">备注<input v-model="form.remark" class="form-input" placeholder="调价依据"></label>
      <button class="btn-primary btn-sm" :disabled="working" @click="createVersion">保存草稿</button>
      <button class="btn-default btn-sm" @click="showForm=false">取消</button>
    </div>
    <div class="card price-table-wrap">
      <div v-if="loading" class="price-empty">加载中...</div>
      <div v-else-if="!versions.length" class="price-empty">暂无工价版本</div>
      <table v-else class="data-table price-table">
        <thead><tr><th>路线</th><th>工序</th><th class="text-right">正常工价</th><th>返工倍率</th><th>有效区间</th><th>状态</th><th>制单 / 审批</th><th>操作</th></tr></thead>
        <tbody><tr v-for="item in versions" :key="item.id">
          <td>{{ item.route_name || item.route_id }}</td><td>{{ item.process_name || item.process_id }}</td>
          <td class="text-right"><strong>{{ unitPrice(item.normal_unit_price_micros) }}</strong></td>
          <td><span v-if="item.rework_rate_configured">{{ reworkRate(item.rework_rate_basis_points) }}</span><span v-else class="text-warning">未配置</span></td>
          <td>{{ item.valid_from }}<small>至 {{ item.valid_to || '长期' }}</small></td>
          <td><span class="price-status" :class="'status-'+item.status">{{ statusLabel(item.status) }}</span></td>
          <td>{{ item.created_by_name || '-' }}<small>{{ item.approved_by_name ? `审批：${item.approved_by_name}` : '尚未审批' }}</small></td>
          <td><button v-if="canApprove && item.status==='draft'" class="btn-primary btn-sm" :disabled="working" @click="approve(item)">批准</button></td>
        </tr></tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const status=ref('')
const versions=ref([])
const references=ref([])
const loading=ref(false)
const working=ref(false)
const showForm=ref(false)
const form=ref(emptyForm())
const canPrepare=computed(()=>can('wages:prepare'))
const canApprove=computed(()=>can('wages:approve'))
function localNow(){const date=new Date();date.setMinutes(date.getMinutes()-date.getTimezoneOffset());return date.toISOString().slice(0,16)}
function emptyForm(){return {reference:'',unitPrice:'',validFrom:localNow(),reworkConfigured:false,reworkPercent:'',remark:''}}
function unitPrice(value){return `¥${(Number(value||0)/10000).toFixed(4)}`}
function reworkRate(value){return `${(Number(value||0)/100).toFixed(2)}%`}
function statusLabel(value){return {draft:'草稿',approved:'已批准',retired:'已结束'}[value]||value}
async function load(){
  loading.value=true
  try{const data=await api.domains.wages.listRoutePriceVersions({status:status.value});versions.value=data.versions||[]}
  catch(error){showToast(error.message||'工价版本加载失败','error')}
  finally{loading.value=false}
}
async function loadReferences(){
  if(!canPrepare.value&&!canApprove.value)return
  try{const data=await api.domains.wages.getRoutePriceVersionReference();references.value=data.items||[]}
  catch(error){showToast(error.message||'路线工序加载失败','error')}
}
async function createVersion(){
  const [routeId,processId]=(form.value.reference||'').split(':').map(Number)
  if(!routeId||!processId||form.value.unitPrice===''||!form.value.validFrom){showToast('请完整填写路线、工序、工价和生效时间','error');return}
  if(Number(form.value.unitPrice)<=0){showToast('工价必须大于 0','error');return}
  const data={route_id:routeId,process_id:processId,normal_unit_price:form.value.unitPrice,valid_from:form.value.validFrom.replace('T',' ')+':00',remark:form.value.remark.trim()}
  if(form.value.reworkConfigured)data.rework_rate_basis_points=Math.round(Number(form.value.reworkPercent||0)*100)
  working.value=true
  try{await api.domains.wages.createRoutePriceVersion(data);showToast('工价草稿已创建');form.value=emptyForm();showForm.value=false;await load()}
  catch(error){showToast(error.message||'创建失败','error')}
  finally{working.value=false}
}
async function approve(item){
  if(!window.confirm(`批准 ${item.route_name} / ${item.process_name} 的新工价版本？`))return
  working.value=true
  try{await api.domains.wages.approveRoutePriceVersion(item.id,item.row_version);showToast('工价版本已批准');await load()}
  catch(error){showToast(error.message||'批准失败','error')}
  finally{working.value=false}
}
onMounted(()=>{load();loadReferences()})
</script>

<style scoped>
.price-toolbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.price-toolbar h3{margin:0;font-size:18px}.price-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.price-actions{display:flex;gap:8px}.price-actions .form-input{width:140px}.price-form{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;padding:12px;margin-bottom:12px;background:var(--bg-secondary);border-top:1px solid var(--border-light);border-bottom:1px solid var(--border-light)}.price-form label{display:flex;flex-direction:column;gap:4px;color:var(--text-placeholder);font-size:12px}.price-form label:first-child{min-width:240px}.price-form .rate-toggle{flex-direction:row;align-items:center;padding-bottom:8px}.price-form .remark{flex:1;min-width:180px}.price-table-wrap{padding:0;overflow-x:auto;border-radius:8px}.price-table{width:100%;min-width:960px}.price-table small{display:block;margin-top:2px;color:var(--text-placeholder)}.price-empty{text-align:center;padding:48px;color:var(--text-placeholder)}.price-status{display:inline-block;padding:2px 7px;border-radius:4px;background:var(--bg-secondary);font-size:12px}.status-approved{color:var(--success);background:var(--success-light)}.status-retired{color:var(--text-placeholder)}.text-right{text-align:right}@media(max-width:760px){.price-toolbar{flex-direction:column}.price-form label,.price-form label:first-child,.price-form .remark{width:100%;min-width:0}}
</style>
