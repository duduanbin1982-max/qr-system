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
import { useProcessQualityTaskDisposal } from '@/composables/quality/useProcessQualityTaskDisposal.js'

const props = defineProps({ keyword: { type: String, default: '' } })
const emit = defineEmits(['summary', 'waived'])

const {
  PAGE_SIZE,
  tasks,
  summary,
  status,
  page,
  total,
  selectedTaskIds,
  showWaiver,
  waiving,
  waiverPreviewing,
  waiverPreview,
  waiverForm,
  pages,
  waiverPolicy,
  canWaiveLive,
  disposableTasks,
  allPendingSelected,
  waiverReasonOptions,
  emptyText,
  waiverTitle,
  waiverTargetLabel,
  pageCount,
  reload,
  changeStatus,
  changePage,
  toggleTask,
  toggleAll,
  waiverScopeForTask,
  canWaiveTask,
  orderStatusLabel,
  orderStatusText,
  waiverReasonLabel,
  waiverPayload,
  openWaiverPreview,
  openWaiver,
  openOrderWaiver,
  saveWaiver,
  taskAgeText,
  taskAgeClass
} = useProcessQualityTaskDisposal(props, emit)

defineExpose({ reload })
</script>

<style scoped>
.pqe-note{padding:10px 12px;margin-bottom:var(--space-3);border-left:3px solid var(--primary);background:var(--primary-light);color:var(--text-secondary);font-size:var(--text-sm)}.pqe-disposal-summary{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:var(--space-3);margin-bottom:var(--space-3)}.pqe-disposal-summary>div{border:1px solid var(--border);padding:10px 12px;background:var(--bg-card)}.pqe-disposal-summary strong{display:block;font-size:var(--text-lg)}.pqe-disposal-summary span{color:var(--text-placeholder);font-size:var(--text-xs-alt)}.pqe-disposal-actions{display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-3);font-size:var(--text-sm)}.pqe-status-filter{width:150px}.pqe-wide{min-width:1320px}.cell-muted{margin-top:3px;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.action-cell{white-space:nowrap}.action-cell .btn+.btn{margin-left:6px}.pqe-pagination{display:flex;align-items:center;justify-content:flex-end;gap:var(--space-3);padding-top:var(--space-3);color:var(--text-secondary);font-size:var(--text-sm)}.pqe-modal{width:min(720px,94vw);max-height:88vh;display:flex;flex-direction:column}.pqe-modal .modal-body{overflow:auto}.pqe-full-label{display:flex;flex-direction:column;gap:6px;margin:var(--space-3) 0;color:var(--text-secondary);font-size:var(--text-sm)}.pqe-review-meta{padding:10px 12px;background:var(--bg-hover);font-weight:600}.pqe-live-warning{border:1px solid var(--danger);background:var(--danger-light);color:var(--danger)}.pqe-waiver-impact{margin-top:var(--space-3);border:1px solid var(--border)}.pqe-impact-summary{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--border)}.pqe-impact-summary>div{padding:10px 12px;text-align:center}.pqe-impact-summary strong{display:block;font-size:var(--text-lg)}.pqe-impact-summary span{color:var(--text-placeholder);font-size:var(--text-xs-alt)}.pqe-impact-orders{max-height:160px;overflow:auto}.pqe-impact-orders>div{display:grid;grid-template-columns:minmax(130px,1fr) 80px minmax(180px,1.4fr);gap:var(--space-2);padding:8px 12px;border-bottom:1px solid var(--border);font-size:var(--text-sm)}.pqe-impact-orders>div:last-child{border-bottom:0}.pqe-impact-warnings{margin:0;padding:10px 30px;border-top:1px solid var(--border);background:var(--warning-light);color:var(--text-secondary);font-size:var(--text-sm)}
@media(max-width:900px){.pqe-disposal-summary{grid-template-columns:1fr}.pqe-disposal-actions{align-items:flex-start;flex-direction:column}.pqe-pagination{justify-content:flex-start;flex-wrap:wrap}.pqe-impact-summary{grid-template-columns:repeat(2,1fr)}.pqe-impact-orders>div{grid-template-columns:1fr}}
</style>
