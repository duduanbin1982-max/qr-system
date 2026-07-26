<template>
  <div class="pqe-task-disposal">
    <div class="pqe-note">历史任务由质量人员按原因类型处置；生产中或待生产订单属于例外放行，仅系统管理员可操作。</div>
    <div class="pqe-disposal-summary">
      <div><strong>{{ summary.required_pending || 0 }}</strong><span>待处理必评</span></div>
      <div><strong>{{ summary.overdue_24h || 0 }}</strong><span>必评超24小时</span></div>
      <div><strong class="text-danger">{{ summary.overdue_72h || 0 }}</strong><span>必评超72小时</span></div>
      <div><strong>{{ summary.completed_order_required || 0 }}</strong><span>已完成订单遗留</span></div>
      <div><strong>{{ summary.affected_workers || 0 }}</strong><span>受影响员工</span></div>
    </div>
    <div class="pqe-disposal-actions">
      <select v-model="status" class="form-input pqe-status-filter" @change="changeStatus"><option value="pending">待处置</option><option value="waived">已豁免</option><option value="audit">永久审计</option></select>
      <label v-if="status === 'pending'"><input type="checkbox" :checked="allPendingSelected" @change="toggleAll($event.target.checked)"> 全选当前可处置任务</label>
      <span v-if="status === 'pending'">已选择 {{ selectedTaskIds.length }} 条</span>
      <button v-if="status === 'pending'" class="btn btn-warning btn-sm" :disabled="!selectedTaskIds.length" @click="openWaiver(selectedTaskIds)">豁免选中任务</button>
    </div>
    <div class="table-wrap"><table v-if="tasks.length" class="data-table pqe-wide"><thead><tr><th v-if="status === 'pending'"></th><th>生成时间</th><th>订单/工件</th><th>订单状态</th><th>上游工序</th><th>评价人</th><th>要求</th><th>时效</th><th>状态/处置</th><th>操作</th></tr></thead>
      <tbody><tr v-for="task in tasks" :key="`${task.audit_record ? 'audit' : 'task'}-${task.id}`"><td v-if="status === 'pending'"><input type="checkbox" :disabled="!canWaiveTask(task)" :checked="selectedTaskIds.includes(task.id)" @change="toggleTask(task.id, $event.target.checked)"></td><td>{{ task.created_at }}</td><td><code>{{ task.order_no }}</code><div class="cell-muted">{{ task.serial_no || '订单模式' }}</div></td><td><span class="badge" :class="waiverScopeForTask(task) === 'live' ? 'badge-warning' : 'badge-info'">{{ orderStatusText(task) }}</span></td><td>{{ task.target_process_name }}</td><td>{{ task.evaluator_name }}</td><td><span class="badge" :class="task.is_required ? 'badge-warning' : 'badge-info'">{{ task.is_required ? '必评' : '选评' }}</span></td><td><span :class="taskAgeClass(task)">{{ taskAgeText(task) }}</span></td><td><template v-if="task.status === 'waived' || task.audit_record"><span class="badge badge-info">{{ task.audit_record ? '永久审计' : '已豁免' }}</span><div class="cell-muted">{{ task.waived_by_name || '-' }} · {{ task.waived_at || '-' }}</div><div class="cell-muted">{{ waiverReasonLabel(task.waiver_reason_code) }}</div><div class="cell-muted">{{ task.waiver_reason || '-' }}</div></template><span v-else class="badge badge-warning">待处置</span></td><td class="action-cell"><template v-if="task.status === 'pending' && canWaiveTask(task)"><button class="btn btn-default btn-sm" @click="openWaiver([task.id])">豁免</button><button v-if="task.is_required" class="btn btn-warning btn-sm" @click="openOrderWaiver(task)">本订单必评</button></template><span v-else-if="task.status === 'pending'" class="cell-muted">需生产中豁免权限</span><span v-else-if="task.audit_record" class="cell-muted">只读留痕</span></td></tr></tbody>
    </table><div v-else class="empty"><div class="empty-text">暂无{{ emptyText }}记录</div></div></div>
    <div v-if="total" class="pqe-pagination"><span>共 {{ total }} 条</span><button class="btn btn-default btn-sm" :disabled="page <= 1" @click="changePage(-1)">上一页</button><span>第 {{ page }} / {{ pages }} 页</span><button class="btn btn-default btn-sm" :disabled="page >= pages" @click="changePage(1)">下一页</button></div>

    <div v-if="showWaiver" class="modal-overlay"><div class="modal pqe-modal"><div class="modal-header"><span>{{ waiverTitle }}</span><span class="modal-close" @click="showWaiver=false">&times;</span></div><div class="modal-body"><div class="pqe-review-meta" :class="{ 'pqe-live-warning': waiverForm.scope === 'live' }">{{ waiverTargetLabel }}</div><div v-if="waiverPreview" class="pqe-waiver-impact"><div class="pqe-impact-summary"><div><strong>{{ waiverPreview.task_count }}</strong><span>影响任务</span></div><div><strong>{{ waiverPreview.required_count }}</strong><span>必评</span></div><div><strong>{{ waiverPreview.optional_count }}</strong><span>选评</span></div><div><strong>{{ waiverPreview.affected_worker_count }}</strong><span>影响员工</span></div></div><div class="pqe-impact-orders"><div v-for="order in waiverPreview.orders" :key="order.order_id"><code>{{ order.order_no }}</code><span>{{ orderStatusLabel(order.order_status) }}</span><span>{{ order.task_count }} 条（必评 {{ order.required_count }} / 选评 {{ order.optional_count }}）</span></div></div><ul v-if="waiverPreview.warnings.length" class="pqe-impact-warnings"><li v-for="warning in waiverPreview.warnings" :key="warning">{{ warning }}</li></ul></div><label class="pqe-full-label">豁免原因类型<select v-model="waiverForm.reasonCode" class="form-input"><option value="">请选择</option><option v-for="option in waiverReasonOptions" :key="option.code" :value="option.code">{{ option.label }}</option></select></label><label class="pqe-full-label">豁免说明<textarea v-model="waiverForm.reason" rows="4" class="form-input" :placeholder="waiverForm.scope === 'live' ? '至少10个字符，填写授权人及现场放行依据' : '至少2个字符，填写历史任务无法补评的依据'"></textarea></label></div><div class="modal-footer"><button class="btn btn-default" :disabled="waiving" @click="showWaiver=false">取消</button><button class="btn btn-warning" :disabled="waiving || !waiverPreview?.can_submit" @click="saveWaiver">{{ waiving ? '提交中...' : '确认豁免' }}</button></div></div></div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const props = defineProps({ keyword: { type: String, default: '' } })
const emit = defineEmits(['summary', 'waived'])
const PAGE_SIZE = 50
const tasks = ref([]), summary = ref({}), status = ref('pending')
const page = ref(1), total = ref(0), selectedTaskIds = ref([])
const showWaiver = ref(false), waiving = ref(false), waiverPreviewing = ref(false), waiverPreview = ref(null)
const waiverForm = reactive({ taskIds: [], orderId: null, orderNo: '', scope: '', reasonCode: '', reason: '' })

const pages = computed(() => pageCount(total.value))
const waiverPolicy = computed(() => summary.value.waiver_policy || {})
const canWaiveLive = computed(() => Boolean(waiverPolicy.value.can_waive_live))
const disposableTasks = computed(() => tasks.value.filter(task => task.status === 'pending' && canWaiveTask(task)))
const allPendingSelected = computed(() => status.value === 'pending' && disposableTasks.value.length > 0 && selectedTaskIds.value.length === disposableTasks.value.length)
const waiverReasonOptions = computed(() => waiverForm.scope === 'live' ? (waiverPolicy.value.live_reasons || []) : waiverForm.scope === 'historical' ? (waiverPolicy.value.historical_reasons || []) : [])
const emptyText = computed(() => ({ pending: '待处置', waived: '已豁免', audit: '永久审计' }[status.value] || ''))
const waiverTitle = computed(() => waiverForm.orderId ? '豁免本订单必评任务' : '豁免评价任务')
const waiverTargetLabel = computed(() => { const count = waiverPreview.value?.task_count || waiverForm.taskIds.length; const target = waiverForm.orderId ? `订单 ${waiverForm.orderNo || waiverForm.orderId} 的 ${count} 条待处理必评任务` : `已选择的 ${count} 条待评价任务`; return waiverForm.scope === 'live' ? `${target}属于生产中或待生产订单。` : waiverForm.scope === 'historical' ? `${target}将按历史任务留痕处置。` : `${target}包含不同处置范围，不能提交。` })

function pageCount(value) { return Math.max(1, Math.ceil((Number(value) || 0) / PAGE_SIZE)) }
async function reload({ resetPage = false } = {}) { if (resetPage) page.value = 1; const params = { keyword: props.keyword, page: page.value, per_page: PAGE_SIZE }; try { const request = status.value === 'audit' ? api.domains.processQualityEvaluations.qualityEvaluationTaskAudits(params) : api.domains.processQualityEvaluations.qualityEvaluationTasks({ ...params, scope: 'all', status: status.value }); const [summaryData, taskData] = await Promise.all([api.domains.processQualityEvaluations.qualityEvaluationTaskDisposalSummary(), request]); const lastPage = pageCount(taskData.total); if (page.value > lastPage) { page.value = lastPage; return reload() } summary.value = summaryData || {}; tasks.value = taskData.items || []; total.value = taskData.total || 0; emit('summary', summary.value); const visibleIds = new Set(tasks.value.filter(task => task.status === 'pending').map(task => task.id)); selectedTaskIds.value = selectedTaskIds.value.filter(id => visibleIds.has(id)) } catch (error) { showToast(error.message || '任务处置数据加载失败', 'error') } }
async function changeStatus() { page.value = 1; selectedTaskIds.value = []; await reload() }
async function changePage(delta) { page.value += delta; selectedTaskIds.value = []; await reload() }
function toggleTask(taskId, checked) { selectedTaskIds.value = checked ? [...new Set([...selectedTaskIds.value, taskId])] : selectedTaskIds.value.filter(id => id !== taskId) }
function toggleAll(checked) { selectedTaskIds.value = checked ? disposableTasks.value.map(task => task.id) : [] }
function waiverScopeForTask(task) { return task.order_deleted_at || ['completed', 'cancelled'].includes(task.order_status) ? 'historical' : 'live' }
function canWaiveTask(task) { return waiverScopeForTask(task) === 'historical' || canWaiveLive.value }
function orderStatusLabel(value) { return { completed: '已完成', cancelled: '已取消', pending: '待生产', producing: '生产中', paused: '已暂停' }[value] || value || '-' }
function orderStatusText(task) { return task.order_deleted_at ? '已归档' : orderStatusLabel(task.order_status) }
function waiverReasonLabel(code) { if (!code || code === 'legacy_unclassified') return '历史记录未分类'; const options = [...(waiverPolicy.value.historical_reasons || []), ...(waiverPolicy.value.live_reasons || [])]; return options.find(option => option.code === code)?.label || code }
function waiverPayload() { return waiverForm.orderId ? { order_id: waiverForm.orderId, required_only: true } : { task_ids: waiverForm.taskIds } }
async function openWaiverPreview(formValues) { if (waiverPreviewing.value) return; waiverPreviewing.value = true; try { const preview = await api.domains.processQualityEvaluations.previewQualityEvaluationTaskWaiver(formValues.orderId ? { order_id: formValues.orderId, required_only: true } : { task_ids: formValues.taskIds }); waiverPreview.value = preview; Object.assign(waiverForm, { ...formValues, scope: preview.waiver_scope, reasonCode: '', reason: '' }); showWaiver.value = true } catch (error) { showToast(error.message || '豁免影响预览失败', 'error') } finally { waiverPreviewing.value = false } }
async function openWaiver(taskIds) { await openWaiverPreview({ taskIds: [...new Set(taskIds)], orderId: null, orderNo: '' }) }
async function openOrderWaiver(task) { await openWaiverPreview({ taskIds: [], orderId: task.order_id, orderNo: task.order_no }) }
async function saveWaiver() { if (!waiverPreview.value?.can_submit) { showToast('当前选择不能提交，请根据风险提示调整任务范围', 'error'); return } if (!waiverForm.reasonCode) { showToast('请选择豁免原因类型', 'error'); return } const minimumLength = waiverForm.scope === 'live' ? 10 : 2; if (waiverForm.reason.trim().length < minimumLength) { showToast(`请填写至少${minimumLength}个字符的豁免说明`, 'error'); return } waiving.value = true; try { const result = await api.domains.processQualityEvaluations.waiveQualityEvaluationTasks({ ...waiverPayload(), reason_code: waiverForm.reasonCode, reason: waiverForm.reason.trim() }); showWaiver.value = false; waiverPreview.value = null; selectedTaskIds.value = []; showToast(`已豁免 ${result.count || 0} 条评价任务`); await reload(); emit('waived') } catch (error) { showToast(error.message || '豁免失败', 'error') } finally { waiving.value = false } }
function taskAgeText(task) { const hours = Math.max(0, Number(task.age_hours) || 0); return task.age_level === 'critical' ? `超时 ${Math.floor(hours)} 小时` : task.age_level === 'warning' ? `已 ${Math.floor(hours)} 小时` : '24小时内' }
function taskAgeClass(task) { return { critical: 'text-danger', warning: 'text-warning' }[task.age_level] || '' }

defineExpose({ reload })
</script>

<style scoped>
.pqe-note{padding:10px 12px;margin-bottom:var(--space-3);border-left:3px solid var(--primary);background:var(--primary-light);color:var(--text-secondary);font-size:var(--text-sm)}.pqe-disposal-summary{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:var(--space-3);margin-bottom:var(--space-3)}.pqe-disposal-summary>div{border:1px solid var(--border);padding:10px 12px;background:var(--bg-card)}.pqe-disposal-summary strong{display:block;font-size:var(--text-lg)}.pqe-disposal-summary span{color:var(--text-placeholder);font-size:var(--text-xs-alt)}.pqe-disposal-actions{display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-3);font-size:var(--text-sm)}.pqe-status-filter{width:150px}.pqe-wide{min-width:1320px}.cell-muted{margin-top:3px;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.action-cell{white-space:nowrap}.action-cell .btn+.btn{margin-left:6px}.pqe-pagination{display:flex;align-items:center;justify-content:flex-end;gap:var(--space-3);padding-top:var(--space-3);color:var(--text-secondary);font-size:var(--text-sm)}.pqe-modal{width:min(720px,94vw);max-height:88vh;display:flex;flex-direction:column}.pqe-modal .modal-body{overflow:auto}.pqe-full-label{display:flex;flex-direction:column;gap:6px;margin:var(--space-3) 0;color:var(--text-secondary);font-size:var(--text-sm)}.pqe-review-meta{padding:10px 12px;background:var(--bg-hover);font-weight:600}.pqe-live-warning{border:1px solid var(--danger);background:var(--danger-light);color:var(--danger)}.pqe-waiver-impact{margin-top:var(--space-3);border:1px solid var(--border)}.pqe-impact-summary{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--border)}.pqe-impact-summary>div{padding:10px 12px;text-align:center}.pqe-impact-summary strong{display:block;font-size:var(--text-lg)}.pqe-impact-summary span{color:var(--text-placeholder);font-size:var(--text-xs-alt)}.pqe-impact-orders{max-height:160px;overflow:auto}.pqe-impact-orders>div{display:grid;grid-template-columns:minmax(130px,1fr) 80px minmax(180px,1.4fr);gap:var(--space-2);padding:8px 12px;border-bottom:1px solid var(--border);font-size:var(--text-sm)}.pqe-impact-orders>div:last-child{border-bottom:0}.pqe-impact-warnings{margin:0;padding:10px 30px;border-top:1px solid var(--border);background:var(--warning-light);color:var(--text-secondary);font-size:var(--text-sm)}
@media(max-width:900px){.pqe-disposal-summary{grid-template-columns:1fr}.pqe-disposal-actions{align-items:flex-start;flex-direction:column}.pqe-pagination{justify-content:flex-start;flex-wrap:wrap}.pqe-impact-summary{grid-template-columns:repeat(2,1fr)}.pqe-impact-orders>div{grid-template-columns:1fr}}
</style>
