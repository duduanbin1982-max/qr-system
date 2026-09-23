import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { scheduleSegments } from '@/composables/gantt/useScheduleSegments.js'

const STANDARD_SCOPE_LABELS = Object.freeze({
  'route_version:product': '路线版本 · 产品专用',
  'route:product': '路线 · 产品专用',
  'process:product': '工序 · 产品专用',
  'route_version:generic': '路线版本 · 通用',
  'route:generic': '路线 · 通用',
  'process:generic': '工序 · 通用',
})

export const BLOCKED_MESSAGES = Object.freeze({
  NO_COMPATIBLE_NODE: '没有满足能力要求的生产节点',
  MISSING_WORK_TIME_STANDARD: '未配置有效标准工时',
  VERSION_BINDING_MISMATCH: '订单、路线和工序版本不一致',
  NODE_CALENDAR_UNAVAILABLE: '生产节点日历没有可用时间',
  LOCKED_TASK_CONFLICT: '锁定任务发生冲突，需要授权解锁',
  SERIAL_ITEM_SPLIT_FORBIDDEN: '单个序列工件不能跨节点拆分',
  BATCH_CAPACITY_EXCEEDED: '批处理数量或批次配置不符合要求',
  QUANTITY_CONSERVATION_FAILED: '排程拆分数量不守恒',
})

function commandKey(prefix, id = 'command') {
  return `${prefix}-${id}-${Date.now()}`
}

function permissionValue(permission) {
  return permission?.value !== false
}

export function useGanttCapacity({
  orders,
  riskLevel,
  productionNodes,
  canGenerateSchedules,
  canAdjustSchedules,
  canLockSchedules,
  canUnlockSchedules,
  canSubmitSchedules,
  canApproveSchedules,
  canRejectSchedules,
  canPublishSchedules,
  canManageDowntime,
}) {
  const viewMode = ref('orders')
  const operationSchedules = ref([])
  const capacityOrders = ref([])
  const capacityLoading = ref(false)
  const capacityProcessFilter = ref('')
  const capacityNodeFilter = ref('')
  const capacityOrderFilter = ref('')
  const capacityRiskFilter = ref('all')
  const generationOrderId = ref('')
  const generationStartDate = ref('')
  const generationRunKey = ref('')
  const replanOrderId = ref('')
  const replanStartAt = ref('')
  const replanReason = ref('根据实际报工、返工和停机动态重排')
  const replanRunKey = ref('')
  const replanResult = ref(null)
  const autoPlanVisible = ref(false)
  const autoPlanStartDate = ref(new Date().toISOString().slice(0, 10))
  const autoPlanLimit = ref(100)
  const autoPlanKey = ref('')
  const autoPlanLoading = ref(false)
  const autoPlanResult = ref(null)
  const downtimeEvents = ref([])
  const downtimeLoading = ref(false)
  const conflictAudit = ref({
    line_conflicts: 0,
    conflicts: [],
    risk_counts: {},
    risk_orders: [],
    delayed_order_count: 0,
    total_delay_minutes: 0,
  })
  const downtimeForm = ref({
    production_node_id: '',
    start_at: '',
    end_at: '',
    reason: '',
  })
  const showAdjustmentModal = ref(false)
  const adjustmentForm = ref({
    revision_item_id: '',
    production_node_id: '',
    planned_start_at: '',
    row_version: 1,
    reason: '',
    idempotency_key: '',
  })

  const capacityNodes = computed(() => productionNodes?.value || [])
  const selectedReplanOrder = computed(() => capacityOrders.value.find(
    item => String(item.id) === String(replanOrderId.value),
  ) || orders.value.find(
    item => String(item.id) === String(replanOrderId.value),
  ) || null)

  const processOptions = computed(() => {
    const seen = new Map()
    capacityNodes.value.forEach((node) => {
      if (!seen.has(node.process_id)) seen.set(node.process_id, node.process_name)
    })
    operationSchedules.value.forEach((row) => {
      if (!seen.has(row.process_id)) seen.set(row.process_id, row.process_name)
    })
    return [...seen.entries()].map(([id, name]) => ({ id, name }))
  })

  const filteredOperations = computed(() => operationSchedules.value.filter((row) => {
    if (
      capacityOrderFilter.value
      && String(row.order_id) !== String(capacityOrderFilter.value)
    ) return false
    if (
      capacityProcessFilter.value
      && String(row.process_id) !== String(capacityProcessFilter.value)
    ) return false
    if (capacityNodeFilter.value) {
      const directMatch = String(row.production_node_id || '') === String(capacityNodeFilter.value)
      const allocationMatch = (row.allocations || []).some(
        allocation => String(allocation.production_node_id || '') === String(capacityNodeFilter.value),
      )
      const segmentMatch = (row.segments || []).some(
        segment => String(segment.production_node_id || '') === String(capacityNodeFilter.value),
      )
      if (!directMatch && !allocationMatch && !segmentMatch) return false
    }
    if (capacityRiskFilter.value === 'conflict' && !Number(row.conflict_count || 0)) return false
    if (capacityRiskFilter.value === 'blocked' && !(
      row.schedule_status === 'blocked' || row.status === 'blocked'
    )) return false
    if (capacityRiskFilter.value === 'critical' && ![
      'overdue', 'high',
    ].includes(operationRiskLevel(row))) return false
    return true
  }))

  const capacitySummary = computed(() => {
    const rows = filteredOperations.value
    return {
      total: rows.length,
      planned: rows.filter(row => row.schedule_status === 'planned' || row.status === 'planned').length,
      blocked: rows.filter(row => row.schedule_status === 'blocked' || row.status === 'blocked').length,
      conflicts: rows.reduce((sum, row) => sum + Number(row.conflict_count || 0), 0),
      minutes: rows.reduce(
        (sum, row) => sum + Number(row.occupied_minutes ?? row.planned_minutes ?? 0),
        0,
      ),
    }
  })

  async function loadCapacity() {
    capacityLoading.value = true
    try {
      const [scheduleData, orderData, auditData] = await Promise.all([
        api.domains.production.listOperationSchedules({ limit: 1000 }),
        api.domains.production.listCapacityOrders({ limit: 1000 }),
        api.domains.production.auditScheduleCapacity({ limit: 1000 }),
      ])
      operationSchedules.value = scheduleData.operations || []
      capacityOrders.value = orderData.orders || orders.value || []
      conflictAudit.value = auditData || conflictAudit.value
      if (!downtimeForm.value.production_node_id && capacityNodes.value.length) {
        downtimeForm.value.production_node_id = capacityNodes.value[0].id
      }
    } catch (error) {
      showToast(error.message || '加载工序排程失败', 'error')
      operationSchedules.value = []
    } finally {
      capacityLoading.value = false
    }
  }

  async function loadDowntime() {
    downtimeLoading.value = true
    try {
      const result = await api.domains.production.listScheduleDowntime({ limit: 500 })
      downtimeEvents.value = result.events || []
    } catch (error) {
      showToast(error.message || '加载停机记录失败', 'error')
      downtimeEvents.value = []
    } finally {
      downtimeLoading.value = false
    }
  }

  async function setViewMode(mode) {
    viewMode.value = mode
    if (mode === 'operations' && !operationSchedules.value.length && !capacityLoading.value) {
      await loadCapacity()
    }
    if (mode === 'operations' && !downtimeLoading.value) await loadDowntime()
  }

  async function createDowntime() {
    if (!permissionValue(canManageDowntime)) return null
    const form = downtimeForm.value
    if (!Number(form.production_node_id)) {
      showToast('请选择停机生产节点', 'error')
      return null
    }
    if (!form.start_at || !form.end_at) {
      showToast('请填写停机开始和结束时间', 'error')
      return null
    }
    if (new Date(form.end_at) <= new Date(form.start_at)) {
      showToast('停机结束时间必须晚于开始时间', 'error')
      return null
    }
    if (!String(form.reason || '').trim()) {
      showToast('停机原因必填', 'error')
      return null
    }
    try {
      const result = await api.domains.production.createScheduleNodeDowntime({
        production_node_id: Number(form.production_node_id),
        start_at: form.start_at,
        end_at: form.end_at,
        reason: String(form.reason).trim(),
      })
      showToast('停机记录已保存')
      form.start_at = ''
      form.end_at = ''
      form.reason = ''
      await loadDowntime()
      return result
    } catch (error) {
      showToast(error.message || '保存停机记录失败', 'error')
      return null
    }
  }

  async function cancelDowntime(event) {
    if (!permissionValue(canManageDowntime)) return null
    try {
      const result = await api.domains.production.cancelScheduleDowntime(event.id)
      showToast('停机记录已取消')
      await loadDowntime()
      return result
    } catch (error) {
      showToast(error.message || '取消停机记录失败', 'error')
      return null
    }
  }

  function startGeneration(order) {
    generationOrderId.value = order?.id || ''
    generationStartDate.value = order?.plan_start || new Date().toISOString().slice(0, 10)
    generationRunKey.value = commandKey('schedule', order?.id || 'order')
  }

  function prepareGeneration(orderId) {
    const order = capacityOrders.value.find(item => String(item.id) === String(orderId))
      || orders.value.find(item => String(item.id) === String(orderId))
    if (order) startGeneration(order)
  }

  async function generateSchedule() {
    if (!permissionValue(canGenerateSchedules)) return null
    if (!generationOrderId.value) {
      showToast('请选择订单', 'error')
      return null
    }
    try {
      const result = await api.domains.production.generateOrderOperationSchedule(
        generationOrderId.value,
        {
          start_date: generationStartDate.value,
          schedule_run_key: generationRunKey.value,
        },
      )
      showToast('工序排程草稿已生成')
      await loadCapacity()
      return result
    } catch (error) {
      showToast(error.message || '生成工序排程失败', 'error')
      return null
    }
  }

  function startDynamicReplan(order) {
    replanOrderId.value = order?.id || ''
    const now = new Date()
    const pad = value => String(value).padStart(2, '0')
    replanStartAt.value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`
    replanRunKey.value = commandKey('dynamic-replan', order?.id || 'order')
    replanResult.value = null
  }

  function prepareDynamicReplan(orderId) {
    const order = capacityOrders.value.find(item => String(item.id) === String(orderId))
      || orders.value.find(item => String(item.id) === String(orderId))
    if (order) startDynamicReplan(order)
  }

  async function dynamicReplanSchedule() {
    if (!permissionValue(canGenerateSchedules)) return null
    if (!replanOrderId.value) {
      showToast('请选择订单', 'error')
      return null
    }
    if (!String(replanReason.value || '').trim()) {
      showToast('动态重排原因必填', 'error')
      return null
    }
    try {
      const result = await api.domains.production.dynamicReplanOrderSchedule(replanOrderId.value, {
        start_at: replanStartAt.value,
        schedule_run_key: replanRunKey.value,
        reason: String(replanReason.value).trim(),
      })
      replanResult.value = result
      showToast('已按实际生产事实生成动态重排草稿')
      await loadCapacity()
      return result
    } catch (error) {
      showToast(error.message || '动态重排失败', 'error')
      return null
    }
  }

  function prepareAutoPlan() {
    autoPlanVisible.value = true
    autoPlanStartDate.value = new Date().toISOString().slice(0, 10)
    autoPlanLimit.value = 100
    autoPlanKey.value = commandKey('auto-plan')
    autoPlanResult.value = null
  }

  async function runAutoPlan() {
    if (!permissionValue(canGenerateSchedules)) return null
    const startDate = String(autoPlanStartDate.value || '').trim()
    const runKey = String(autoPlanKey.value || '').trim()
    const limit = Number(autoPlanLimit.value)
    if (!startDate) {
      showToast('请填写自动排程开始日期', 'error')
      return null
    }
    if (!runKey) {
      showToast('请填写自动排程幂等键', 'error')
      return null
    }
    if (!Number.isInteger(limit) || limit < 1 || limit > 1000) {
      showToast('自动排程订单数必须在1到1000之间', 'error')
      return null
    }
    autoPlanLoading.value = true
    try {
      const result = await api.domains.production.autoPlanSchedule({
        start_date: startDate,
        auto_plan_key: runKey,
        limit,
      })
      autoPlanResult.value = result
      if (result?.status === 'completed') {
        showToast(`自动排程完成：${result.queue_count || 0} 个订单`)
      } else if (result?.status === 'failed') {
        showToast(`自动排程完成但有失败订单：${result.failed_count || 0} 个`, 'error')
      } else {
        showToast('自动排程已返回结果')
      }
      await loadCapacity()
      return result
    } catch (error) {
      showToast(error.message || '自动排程失败', 'error')
      return null
    } finally {
      autoPlanLoading.value = false
    }
  }

  function nodeLabel(row) {
    if (row.node_code || row.node_name) {
      return [row.node_code, row.node_name].filter(Boolean).join(' · ')
    }
    return row.production_node_id ? `生产节点 #${row.production_node_id}` : '未分配'
  }

  function allocationLabel(allocation) {
    const node = [allocation.node_code, allocation.node_name].filter(Boolean).join(' · ')
      || `生产节点 #${allocation.production_node_id}`
    const quantity = Number(allocation.quantity || 0)
    return `${node} × ${quantity}`
  }

  function operationSegments(row) {
    return scheduleSegments(row)
  }

  function blockedCode(row) {
    return String(row.blocked_code || row.error_code || '').trim()
  }

  function blockedMessage(row) {
    const code = blockedCode(row)
    return BLOCKED_MESSAGES[code] || row.blocked_reason || row.reason || '前置条件不满足'
  }

  function standardScopeLabel(scope) {
    const value = String(scope || '').trim()
    return STANDARD_SCOPE_LABELS[value] || value || '-'
  }

  function operationRisk(row) {
    if (row?.candidate_revision && row?.risk_level) {
      return {
        risk_level: row.risk_level,
        risk_reason: row.risk_reason || '候选排程版本风险快照',
        delay_minutes: Number(row.delay_minutes || 0),
      }
    }
    const order = orders.value.find(item => String(item.id) === String(row.order_id))
      || capacityOrders.value.find(item => String(item.id) === String(row.order_id))
    return order || { risk_level: 'none', risk_reason: '订单交期风险信息尚未加载' }
  }

  function operationRiskLevel(row) {
    const order = operationRisk(row)
    return riskLevel ? riskLevel(order) : (order.risk_level || 'none')
  }

  function prepareAdjustment(row) {
    if (!permissionValue(canAdjustSchedules)) return false
    if (!row?.revision_item_id) {
      showToast('该排程事实尚未建立可调整的修订条目', 'error')
      return false
    }
    adjustmentForm.value = {
      revision_item_id: row.revision_item_id,
      production_node_id: row.production_node_id || '',
      planned_start_at: String(row.planned_start_at || '').replace(' ', 'T').slice(0, 16),
      row_version: Number(row.revision_item_row_version || 1),
      reason: '',
      idempotency_key: commandKey('schedule-adjust', row.revision_item_id),
    }
    showAdjustmentModal.value = true
    return true
  }

  async function saveOperationAdjustment() {
    if (!permissionValue(canAdjustSchedules)) return null
    const form = adjustmentForm.value
    if (!Number(form.revision_item_id) || !Number(form.production_node_id)) {
      showToast('排程修订条目和生产节点必填', 'error')
      return null
    }
    if (!form.planned_start_at) {
      showToast('计划开始时间必填', 'error')
      return null
    }
    if (!String(form.reason || '').trim()) {
      showToast('人工调整原因必填', 'error')
      return null
    }
    try {
      const result = await api.domains.production.adjustScheduleItem(
        Number(form.revision_item_id),
        {
          production_node_id: Number(form.production_node_id),
          planned_start_at: form.planned_start_at,
          row_version: Number(form.row_version || 1),
          reason: String(form.reason).trim(),
          idempotency_key: String(form.idempotency_key).trim(),
        },
      )
      showToast('已生成新的排程草稿修订版')
      showAdjustmentModal.value = false
      await loadCapacity()
      return result
    } catch (error) {
      showToast(error.message || '调整排程失败', 'error')
      return null
    }
  }

  async function runItemCommand(row, action, reason = '') {
    const permission = action === 'lock' ? canLockSchedules : canUnlockSchedules
    if (!permissionValue(permission)) return null
    if (!row?.revision_item_id) {
      showToast('该排程事实缺少修订条目，不能执行锁定操作', 'error')
      return null
    }
    const actionReason = String(
      reason || window.prompt(`请输入${action === 'lock' ? '锁定' : '解锁'}原因：`, '') || '',
    ).trim()
    if (!actionReason) {
      showToast('锁定或解锁原因必填', 'error')
      return null
    }
    const method = action === 'lock'
      ? api.domains.production.lockScheduleItem
      : api.domains.production.unlockScheduleItem
    try {
      const result = await method(row.revision_item_id, {
        reason: actionReason,
        idempotency_key: commandKey(`schedule-${action}`, row.revision_item_id),
      })
      showToast(action === 'lock' ? '排程任务已锁定' : '排程任务已解锁')
      await loadCapacity()
      return result
    } catch (error) {
      showToast(error.message || '排程锁定操作失败', 'error')
      return null
    }
  }

  const lockOperation = (row, reason = '') => runItemCommand(row, 'lock', reason)
  const unlockOperation = (row, reason = '') => runItemCommand(row, 'unlock', reason)

  async function runRevisionCommand(row, action, reason = '') {
    const permissions = {
      submit: canSubmitSchedules,
      approve: canApproveSchedules,
      reject: canRejectSchedules,
      publish: canPublishSchedules,
    }
    if (!permissionValue(permissions[action])) return null
    const revisionId = Number(row?.schedule_revision_id)
    if (!revisionId) {
      showToast('该排程事实缺少修订版本', 'error')
      return null
    }
    const methods = {
      submit: api.domains.production.submitScheduleRevision,
      approve: api.domains.production.approveScheduleRevision,
      reject: api.domains.production.rejectScheduleRevision,
      publish: api.domains.production.publishScheduleRevision,
    }
    const actionReason = String(
      reason || window.prompt('请输入本次排程版本操作原因：', '') || '',
    ).trim()
    if (!actionReason) {
      showToast('排程版本操作原因必填', 'error')
      return null
    }
    const payload = {
      reason: actionReason,
      idempotency_key: commandKey(`schedule-${action}`, revisionId),
    }
    try {
      const result = await methods[action](revisionId, payload)
      const labels = { submit: '已提交审批', approve: '已批准', reject: '已驳回', publish: '已发布' }
      showToast(`排程版本${labels[action]}`)
      await loadCapacity()
      return result
    } catch (error) {
      showToast(error.message || '排程版本操作失败', 'error')
      return null
    }
  }

  function revisionState(row) {
    const lifecycle = String(row?.revision_status || '').trim()
    const approval = String(row?.revision_approval_status || 'draft').trim()
    if (lifecycle === 'published') return 'published'
    if (lifecycle === 'superseded') return 'superseded'
    if (lifecycle === 'cancelled') return 'cancelled'
    if (approval === 'submitted') return 'pending_approval'
    if (approval === 'approved') return 'approved'
    if (approval === 'rejected') return 'rejected'
    return 'draft'
  }

  function revisionStatusLabel(row) {
    return {
      draft: '草稿',
      pending_approval: '待审批',
      approved: '已批准待发布',
      rejected: '已驳回',
      published: '已发布',
      superseded: '已取代',
      cancelled: '已取消',
    }[revisionState(row)] || '已排程'
  }

  return {
    viewMode,
    capacityNodes,
    capacityOrders,
    selectedReplanOrder,
    operationSchedules,
    capacityLoading,
    capacityProcessFilter,
    capacityNodeFilter,
    capacityOrderFilter,
    capacityRiskFilter,
    processOptions,
    filteredOperations,
    capacitySummary,
    loadCapacity,
    setViewMode,
    generationOrderId,
    generationStartDate,
    generationRunKey,
    startGeneration,
    prepareGeneration,
    generateSchedule,
    replanOrderId,
    replanStartAt,
    replanReason,
    replanRunKey,
    replanResult,
    startDynamicReplan,
    prepareDynamicReplan,
    dynamicReplanSchedule,
    autoPlanVisible,
    autoPlanStartDate,
    autoPlanLimit,
    autoPlanKey,
    autoPlanLoading,
    autoPlanResult,
    prepareAutoPlan,
    runAutoPlan,
    downtimeEvents,
    downtimeLoading,
    conflictAudit,
    downtimeForm,
    loadDowntime,
    createDowntime,
    cancelDowntime,
    showAdjustmentModal,
    adjustmentForm,
    prepareAdjustment,
    saveOperationAdjustment,
    lockOperation,
    unlockOperation,
    submitRevision: (row, reason = '') => runRevisionCommand(row, 'submit', reason),
    approveRevision: (row, reason = '') => runRevisionCommand(row, 'approve', reason),
    rejectRevision: (row, reason = '') => runRevisionCommand(row, 'reject', reason),
    publishRevision: (row, reason = '') => runRevisionCommand(row, 'publish', reason),
    revisionState,
    revisionStatusLabel,
    nodeLabel,
    allocationLabel,
    operationSegments,
    blockedCode,
    blockedMessage,
    standardScopeLabel,
    operationRisk,
    operationRiskLevel,
  }
}
