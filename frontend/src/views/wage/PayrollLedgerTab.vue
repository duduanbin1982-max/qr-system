<template>
  <div>
    <div class="payroll-toolbar">
      <div>
        <h3>工资批次台账</h3>
        <p>生产统计月按每日 07:00 切分；锁定和确认必须由非制单人员执行。</p>
      </div>
      <div class="payroll-toolbar-actions">
        <input v-model="month" type="month" class="form-input" @change="load">
        <select v-model="status" class="form-input" @change="load">
          <option value="">全部状态</option>
          <option v-for="item in statusOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <button class="btn-default btn-sm" @click="load">刷新</button>
        <button v-if="canPrepare" class="btn-primary btn-sm" :disabled="working" @click="createBatch">生成批次</button>
      </div>
    </div>

    <div class="payroll-summary">
      <div><span>批次数</span><strong>{{ batches.length }}</strong></div>
      <div><span>待处理异常</span><strong class="text-warning">{{ pendingExceptions }}</strong></div>
      <div><span>已确认版本</span><strong class="text-success">{{ confirmedCount }}</strong></div>
      <div><span>筛选月应发</span><strong>{{ money(monthTotal) }}</strong></div>
    </div>

    <div class="card payroll-table-wrap">
      <div v-if="loading" class="payroll-empty">加载中...</div>
      <div v-else-if="!batches.length" class="payroll-empty">暂无工资批次</div>
      <table v-else class="data-table payroll-table">
        <thead><tr>
          <th>工资月 / 版本</th><th>状态</th><th>来源</th><th>记录</th><th>异常</th>
          <th class="text-right">应发工资</th><th>制单人</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="batch in batches" :key="batch.id" :class="{selected:selectedId===batch.id}">
            <td><strong>{{ batch.payroll_month }} / V{{ batch.version }}</strong></td>
            <td><span class="payroll-status" :class="'status-'+batch.status">{{ statusLabel(batch.status) }}</span></td>
            <td>{{ batch.legacy_imported ? 'Legacy 快照' : '版本化计算' }}</td>
            <td>{{ batch.priced_record_count }} / {{ batch.source_record_count }}</td>
            <td :class="{'text-warning':batch.exception_count}">{{ batch.exception_count }}</td>
            <td class="text-right"><strong>{{ money(batch.payable_wage_cents) }}</strong></td>
            <td>{{ batch.prepared_by_name || batch.prepared_user_name || '-' }}</td>
            <td>
              <div class="payroll-row-actions">
                <button class="btn-default btn-sm" @click="openBatch(batch)">查看</button>
                <button v-if="canPrepare && editable(batch)" class="btn-default btn-sm" :disabled="working" @click="regenerate(batch)">重算</button>
                <button v-if="canPrepare && canSubmit(batch)" class="btn-primary btn-sm" :disabled="working" @click="submit(batch)">提交</button>
                <button v-if="canApprove && batch.status==='review_pending'" class="btn-primary btn-sm" :disabled="working" @click="lock(batch)">锁定</button>
                <button v-if="canApprove && batch.status==='locked'" class="btn-primary btn-sm" :disabled="working" @click="confirmBatch(batch)">确认</button>
                <button v-if="canExport && ['locked','confirmed'].includes(batch.status)" class="btn-default btn-sm" @click="exportBatch(batch)">导出</button>
                <button v-if="canPrepare && batch.status==='confirmed' && !batch.superseded_by_batch_id" class="btn-default btn-sm" :disabled="working" @click="revise(batch)">修订</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="detail" class="payroll-detail">
      <div class="payroll-detail-header">
        <div>
          <h3>{{ detail.batch.payroll_month }} / V{{ detail.batch.version }} 明细</h3>
          <p>{{ detail.batch.period_start }} 至 {{ detail.batch.period_end }}，数据截止 {{ detail.batch.source_cutoff_at }}</p>
        </div>
        <button class="btn-default btn-sm" @click="detail=null;selectedId=null">关闭</button>
      </div>
      <table class="data-table payroll-table">
        <thead><tr><th>员工</th><th>工号</th><th>正常数量</th><th>返工数量</th><th class="text-right">正常工资</th><th class="text-right">返工工资</th><th class="text-right">调整</th><th class="text-right">应发</th></tr></thead>
        <tbody>
          <tr v-for="line in detail.lines" :key="line.id">
            <td>{{ line.employee_name_snapshot }}</td><td>{{ line.employee_no_snapshot || '-' }}</td>
            <td>{{ line.normal_quantity }}</td><td>{{ line.rework_quantity }}</td>
            <td class="text-right">{{ money(line.normal_wage_cents) }}</td><td class="text-right">{{ money(line.rework_wage_cents) }}</td>
            <td class="text-right">{{ money(line.bonus_cents + line.allowance_cents - line.deduction_cents) }}</td>
            <td class="text-right"><strong>{{ money(line.payable_wage_cents) }}</strong></td>
          </tr>
        </tbody>
      </table>
      <div v-if="detail.exceptions && detail.exceptions.length" class="payroll-detail-note">
        当前版本有 {{ detail.exceptions.length }} 条工资异常，请在“异常处理”中完成双人复核后再重算。
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const now = new Date()
const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
const status = ref('')
const batches = ref([])
const loading = ref(false)
const working = ref(false)
const selectedId = ref(null)
const detail = ref(null)
const canPrepare = computed(() => can('wages:prepare'))
const canApprove = computed(() => can('wages:approve'))
const canExport = computed(() => can('wages:export'))
const statusOptions = [
  { value:'draft', label:'草稿' }, { value:'exceptions_pending', label:'待异常处理' },
  { value:'review_pending', label:'待复核' }, { value:'locked', label:'已锁定' },
  { value:'confirmed', label:'已确认' }, { value:'voided', label:'已作废' },
]
const pendingExceptions = computed(() => batches.value.reduce((sum, item) => sum + Number(item.exception_count || 0), 0))
const confirmedCount = computed(() => batches.value.filter(item => item.status === 'confirmed').length)
const monthTotal = computed(() => batches.value.filter(item => !item.superseded_by_batch_id && item.status !== 'voided').reduce((sum, item) => sum + Number(item.payable_wage_cents || 0), 0))

function money(cents) { return `¥${(Number(cents || 0) / 100).toFixed(2)}` }
function statusLabel(value) { return statusOptions.find(item => item.value === value)?.label || value }
function editable(batch) { return ['draft', 'exceptions_pending'].includes(batch.status) && !batch.legacy_imported }
function canSubmit(batch) { return batch.status === 'draft' && !batch.exception_count && !batch.legacy_imported }
function idempotency(prefix) { return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}` }

async function load() {
  loading.value = true
  try {
    const data = await api.domains.wages.listPayrollBatches({ payroll_month: month.value, status: status.value })
    batches.value = data.batches || []
  } catch (error) { showToast(error.message || '工资批次加载失败', 'error') }
  finally { loading.value = false }
}
async function createBatch() {
  working.value = true
  try {
    await api.domains.wages.createPayrollBatch({ payroll_month: month.value, idempotency_key: idempotency('payroll-ui') })
    showToast('工资批次已生成')
    await load()
  } catch (error) { showToast(error.message || '生成失败', 'error') }
  finally { working.value = false }
}
async function act(call, success) {
  working.value = true
  try { await call(); showToast(success); await load(); if (selectedId.value) await openBatch({ id:selectedId.value }) }
  catch (error) { showToast(error.message || '操作失败', 'error') }
  finally { working.value = false }
}
function regenerate(batch) { return act(() => api.domains.wages.regeneratePayrollBatch(batch.id, batch.row_version), '批次已重算') }
function submit(batch) { return act(() => api.domains.wages.submitPayrollBatch(batch.id, batch.row_version), '批次已提交复核') }
function lock(batch) { return act(() => api.domains.wages.lockPayrollBatch(batch.id, batch.row_version), '批次已锁定') }
function confirmBatch(batch) {
  if (!window.confirm(`确认 ${batch.payroll_month} / V${batch.version} 工资批次？`)) return
  return act(() => api.domains.wages.confirmPayrollBatch(batch.id, batch.row_version), '批次已确认')
}
function revise(batch) {
  const reason = window.prompt('请输入生成修订版的原因')
  if (!reason?.trim()) return
  return act(() => api.domains.wages.revisePayrollBatch(batch.id, { revision_reason:reason.trim(), idempotency_key:idempotency('payroll-revision') }), '修订版已生成')
}
async function openBatch(batch) {
  selectedId.value = batch.id
  try { detail.value = await api.domains.wages.getPayrollBatch(batch.id) }
  catch (error) { showToast(error.message || '批次明细加载失败', 'error') }
}
function exportBatch(batch) { window.open(`/api/payroll/batches/${batch.id}/export`, '_blank', 'noopener') }

onMounted(load)
</script>

<style scoped>
.payroll-toolbar,.payroll-detail-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.payroll-toolbar h3,.payroll-detail h3{margin:0;font-size:18px}.payroll-toolbar p,.payroll-detail p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.payroll-toolbar-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.payroll-toolbar-actions .form-input{width:145px}.payroll-summary{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));border-top:1px solid var(--border-light);border-bottom:1px solid var(--border-light);margin-bottom:12px}.payroll-summary div{padding:12px 16px;border-right:1px solid var(--border-light)}.payroll-summary div:last-child{border-right:0}.payroll-summary span{display:block;color:var(--text-placeholder);font-size:12px}.payroll-summary strong{display:block;margin-top:4px;font-size:20px}.payroll-table-wrap{padding:0;overflow-x:auto;border-radius:8px}.payroll-table{width:100%;min-width:900px}.payroll-table tr.selected{background:var(--bg-hover)}.payroll-status{display:inline-block;padding:2px 7px;border-radius:4px;font-size:12px;background:var(--bg-secondary)}.status-exceptions_pending{color:var(--warning-dark);background:var(--warning-lighter)}.status-review_pending,.status-locked{color:var(--primary);background:var(--primary-light)}.status-confirmed{color:var(--success);background:var(--success-light)}.status-voided{color:var(--danger);background:var(--danger-light)}.payroll-row-actions{display:flex;gap:5px;min-width:210px;flex-wrap:wrap}.payroll-empty{text-align:center;padding:48px;color:var(--text-placeholder)}.payroll-detail{margin-top:16px;padding-top:16px;border-top:2px solid var(--border-light);overflow-x:auto}.payroll-detail-note{padding:10px 12px;margin-top:10px;border-left:3px solid var(--warning);background:var(--warning-lighter);font-size:12px}.text-right{text-align:right}@media(max-width:800px){.payroll-toolbar{flex-direction:column}.payroll-summary{grid-template-columns:repeat(2,1fr)}.payroll-summary div:nth-child(2){border-right:0}.payroll-toolbar-actions{width:100%}}
</style>
