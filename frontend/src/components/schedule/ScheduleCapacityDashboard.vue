<script setup>
import { computed, ref, watch } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import ProductionNodeQueueBoard from '@/components/schedule/ProductionNodeQueueBoard.vue'

const props = defineProps({
  operations: { type: Array, default: () => [] },
  nodes: { type: Array, default: () => [] },
  orders: { type: Array, default: () => [] },
  audit: { type: Object, default: () => ({}) },
  downtime: { type: Array, default: () => [] },
})

const emit = defineEmits(['filterNode', 'filterOrder', 'openOrder', 'refresh'])

const groupMode = ref('node')
const capacityPeriod = ref('day')
const horizonDays = ref(7)
const anchorDate = ref(new Date().toISOString().slice(0, 10))
const activeWorkbench = ref('capacity')
const revisionDialog = ref(false)
const revisionLoading = ref(false)
const revisionHistory = ref([])
const revisionDetail = ref(null)
const previousRevisionDetail = ref(null)

function parseDate(value) {
  if (!value) return null
  if (value instanceof Date) {
    const cloned = new Date(value.getTime())
    return Number.isNaN(cloned.getTime()) ? null : cloned
  }
  const text = String(value).trim()
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  const parsed = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(text.replace(' ', 'T'))
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function startOfDay(value) {
  const parsed = parseDate(value) || new Date()
  parsed.setHours(0, 0, 0, 0)
  return parsed
}

function addDays(value, days) {
  const result = new Date(value)
  result.setDate(result.getDate() + days)
  return result
}

function isoDate(value) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatDateTime(value) {
  const parsed = parseDate(value)
  if (!parsed) return '-'
  return `${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(parsed.getDate()).padStart(2, '0')} ${String(parsed.getHours()).padStart(2, '0')}:${String(parsed.getMinutes()).padStart(2, '0')}`
}

function formatMinutes(value) {
  const minutes = Math.max(Math.round(Number(value) || 0), 0)
  if (minutes < 60) return `${minutes}分`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return remainder ? `${hours}小时${remainder}分` : `${hours}小时`
}

function overlapMinutes(startAt, endAt, rangeStart, rangeEnd) {
  const start = parseDate(startAt)
  const end = parseDate(endAt)
  if (!start || !end) return 0
  const clippedStart = Math.max(start.getTime(), rangeStart.getTime())
  const clippedEnd = Math.min(end.getTime(), rangeEnd.getTime())
  return Math.max((clippedEnd - clippedStart) / 60000, 0)
}

function operationIntervals(operation) {
  const common = {
    operationId: operation.id || operation.revision_item_id,
    orderId: operation.order_id,
    orderNo: operation.order_no || `订单 #${operation.order_id}`,
    processId: operation.process_id,
    processName: operation.process_name || `工序 #${operation.process_id}`,
    revisionId: operation.schedule_revision_id,
    candidate: Boolean(operation.candidate_revision),
    locked: Boolean(operation.locked),
    riskLevel: operation.risk_level || 'none',
    conflictCount: Number(operation.conflict_count || 0),
  }
  const segments = Array.isArray(operation.segments) ? operation.segments : []
  if (segments.length) {
    return segments.map((segment, index) => ({
      ...common,
      key: `segment:${operation.id || operation.revision_item_id}:${segment.id || index}`,
      nodeId: segment.production_node_id || operation.production_node_id,
      nodeCode: segment.node_code || operation.node_code || operation.node_code_snapshot || '',
      nodeName: segment.node_name || operation.node_name || operation.node_name_snapshot || '',
      startAt: segment.segment_start_at || segment.start_at,
      endAt: segment.segment_end_at || segment.end_at,
      minutes: Number(segment.occupied_minutes || 0),
      quantity: Number(segment.quantity ?? operation.quantity ?? 0),
    }))
  }
  const allocations = Array.isArray(operation.allocations) ? operation.allocations : []
  const timedAllocations = allocations.filter(item => (
    item.allocation_start_at || item.segment_start_at
  ) && (item.allocation_end_at || item.segment_end_at))
  if (timedAllocations.length) {
    return timedAllocations.map((allocation, index) => ({
      ...common,
      key: `allocation:${operation.id || operation.revision_item_id}:${allocation.id || index}`,
      nodeId: allocation.production_node_id || operation.production_node_id,
      nodeCode: allocation.node_code || operation.node_code || '',
      nodeName: allocation.node_name || operation.node_name || '',
      startAt: allocation.allocation_start_at || allocation.segment_start_at,
      endAt: allocation.allocation_end_at || allocation.segment_end_at,
      minutes: Number(allocation.occupied_minutes || 0),
      quantity: Number(allocation.quantity ?? operation.quantity ?? 0),
    }))
  }
  const startAt = operation.planned_start_at || operation.plan_start
  const endAt = operation.planned_end_at || operation.plan_end
  if (!startAt || !endAt || operation.status === 'blocked' || operation.schedule_status === 'blocked') return []
  return [{
    ...common,
    key: `operation:${operation.id || operation.revision_item_id}`,
    nodeId: operation.production_node_id,
    nodeCode: operation.node_code || operation.node_code_snapshot || '',
    nodeName: operation.node_name || operation.node_name_snapshot || '',
    startAt,
    endAt,
    minutes: Number(operation.occupied_minutes || operation.planned_minutes || 0),
    quantity: Number(operation.quantity || operation.scheduled_quantity || 0),
  }]
}

const intervals = computed(() => props.operations.flatMap(operationIntervals).filter(item => (
  parseDate(item.startAt) && parseDate(item.endAt)
)))
const unassignedIntervals = computed(() => intervals.value.filter(item => (
  item.nodeId === null || item.nodeId === undefined || item.nodeId === ''
)))

watch(intervals, (rows) => {
  if (!rows.length) return
  const earliest = rows.reduce((minimum, item) => {
    const date = parseDate(item.startAt)
    return !minimum || date < minimum ? date : minimum
  }, null)
  if (earliest) anchorDate.value = isoDate(earliest)
}, { immediate: true, once: true })

const rangeStart = computed(() => startOfDay(anchorDate.value))
const rangeEnd = computed(() => addDays(rangeStart.value, Number(horizonDays.value || 7)))
const rangeLabel = computed(() => `${isoDate(rangeStart.value)} 至 ${isoDate(addDays(rangeEnd.value, -1))}`)
const timelineWidth = computed(() => Math.max(Number(horizonDays.value || 7) * 144, 720))

const dayTicks = computed(() => Array.from({ length: Number(horizonDays.value || 7) }, (_, index) => {
  const date = addDays(rangeStart.value, index)
  return {
    date: isoDate(date),
    label: `${date.getMonth() + 1}/${date.getDate()}`,
    weekend: [0, 6].includes(date.getDay()),
  }
}))

function groupIdentity(interval) {
  if (groupMode.value === 'process') {
    return [`process:${interval.processId}`, interval.processName]
  }
  if (groupMode.value === 'order') {
    return [`order:${interval.orderId}`, interval.orderNo]
  }
  return [
    `node:${interval.nodeId || 'unassigned'}`,
    [interval.processName, interval.nodeCode, interval.nodeName].filter(Boolean).join(' · ') || '未分配生产节点',
  ]
}

const timelineRows = computed(() => {
  const groups = new Map()
  const duration = Math.max(rangeEnd.value - rangeStart.value, 1)
  intervals.value.forEach((interval) => {
    const start = parseDate(interval.startAt)
    const end = parseDate(interval.endAt)
    if (end <= rangeStart.value || start >= rangeEnd.value) return
    const [key, label] = groupIdentity(interval)
    if (!groups.has(key)) groups.set(key, { key, label, bars: [], minutes: 0 })
    const clippedStart = Math.max(start.getTime(), rangeStart.value.getTime())
    const clippedEnd = Math.min(end.getTime(), rangeEnd.value.getTime())
    const bar = {
      ...interval,
      left: ((clippedStart - rangeStart.value.getTime()) / duration) * 100,
      width: Math.max(((clippedEnd - clippedStart) / duration) * 100, 0.35),
      elapsedMinutes: Math.max((clippedEnd - clippedStart) / 60000, 0),
    }
    const group = groups.get(key)
    group.bars.push(bar)
    group.minutes += bar.elapsedMinutes
  })
  return [...groups.values()].sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
})

const calendarsById = computed(() => new Map(
  (props.audit.calendars || []).map(calendar => [String(calendar.id), calendar]),
))

function calendarWorkdays(node) {
  const calendar = calendarsById.value.get(String(node.calendar_id))
  return new Set(String(calendar?.weekly_workdays || '1,2,3,4,5')
    .split(',').map(value => Number(value.trim())).filter(Boolean))
}

function baseCapacity(node, bucketStart, bucketEnd) {
  let minutes = 0
  const workdays = calendarWorkdays(node)
  for (let cursor = startOfDay(bucketStart); cursor < bucketEnd; cursor = addDays(cursor, 1)) {
    if (workdays.has(cursor.getDay() || 7)) minutes += Number(node.capacity_minutes || 0)
  }
  return minutes
}

const unavailability = computed(() => {
  const auditRows = props.audit.capacity_unavailability || []
  if (auditRows.length) return auditRows
  return props.downtime.map(item => ({ ...item, unavailable_type: 'downtime' }))
})

function nodeOccupiedMinutes(nodeId, bucketStart, bucketEnd) {
  return intervals.value.reduce((sum, interval) => (
    String(interval.nodeId || '') === String(nodeId)
      ? sum + overlapMinutes(interval.startAt, interval.endAt, bucketStart, bucketEnd)
      : sum
  ), 0)
}

function nodeUnavailableMinutes(nodeId, bucketStart, bucketEnd) {
  return unavailability.value.reduce((sum, item) => (
    String(item.production_node_id || '') === String(nodeId)
      ? sum + overlapMinutes(item.start_at, item.end_at, bucketStart, bucketEnd)
      : sum
  ), 0)
}

function nodeOvertimeMinutes(nodeId, bucketStart, bucketEnd) {
  return (props.audit.capacity_overrides || []).reduce((sum, item) => (
    String(item.production_node_id || '') === String(nodeId) && item.override_type === 'overtime'
      ? sum + overlapMinutes(item.start_at, item.end_at, bucketStart, bucketEnd)
      : sum
  ), 0)
}

const capacityBuckets = computed(() => {
  if (capacityPeriod.value === 'week') {
    return [{ start: rangeStart.value, end: rangeEnd.value, label: rangeLabel.value }]
  }
  return dayTicks.value.map(day => ({
    start: startOfDay(day.date),
    end: addDays(startOfDay(day.date), 1),
    label: day.label,
  }))
})

const utilizationRows = computed(() => props.nodes.flatMap(node => capacityBuckets.value.map((bucket) => {
  const base = baseCapacity(node, bucket.start, bucket.end)
  const downtimeMinutes = Math.min(nodeUnavailableMinutes(node.id, bucket.start, bucket.end), base)
  const overtimeMinutes = nodeOvertimeMinutes(node.id, bucket.start, bucket.end)
  const available = Math.max(base - downtimeMinutes + overtimeMinutes, 0)
  const occupied = nodeOccupiedMinutes(node.id, bucket.start, bucket.end)
  const overload = Math.max(occupied - available, 0)
  return {
    key: `${node.id}:${bucket.label}`,
    nodeId: node.id,
    label: [node.process_name, node.node_code, node.node_name].filter(Boolean).join(' · '),
    period: bucket.label,
    available,
    occupied,
    remaining: Math.max(available - occupied, 0),
    downtime: downtimeMinutes,
    overtime: overtimeMinutes,
    overload,
    utilization: available > 0 ? (occupied / available) * 100 : (occupied > 0 ? 100 : 0),
  }
})))

const bottleneckRows = computed(() => [...utilizationRows.value]
  .filter(row => row.occupied > 0 || row.downtime > 0)
  .sort((left, right) => (
    Number(right.overload > 0) - Number(left.overload > 0)
    || right.utilization - left.utilization
    || right.downtime - left.downtime
  ))
  .slice(0, 8))

const pendingReplanOrders = computed(() => props.orders.filter(order => order.schedule_replan_required))
const lockedTasks = computed(() => props.operations.filter(operation => operation.locked))
const riskOrders = computed(() => props.audit.risk_orders || [])
const blockedOperations = computed(() => props.operations.filter(operation => (
  operation.status === 'blocked' || operation.schedule_status === 'blocked'
)))

const revisionCards = computed(() => {
  const groups = new Map()
  props.operations.forEach((operation) => {
    const revisionId = Number(operation.schedule_revision_id || 0)
    if (!revisionId) return
    const key = `${operation.order_id}:${revisionId}`
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        revisionId,
        orderId: operation.order_id,
        orderNo: operation.order_no || `订单 #${operation.order_id}`,
        status: operation.revision_status || (operation.candidate_revision ? 'draft' : 'published'),
        approvalStatus: operation.revision_approval_status || '',
        candidate: Boolean(operation.candidate_revision),
        operationCount: 0,
        lockedCount: 0,
        conflictCount: 0,
      })
    }
    const card = groups.get(key)
    card.operationCount += 1
    card.lockedCount += operation.locked ? 1 : 0
    card.conflictCount += Number(operation.conflict_count || 0)
  })
  return [...groups.values()].sort((left, right) => Number(right.revisionId) - Number(left.revisionId))
})

function barTone(bar) {
  if (bar.conflictCount) return '#dc2626'
  if (bar.locked) return '#7c3aed'
  if (bar.candidate) return '#f59e0b'
  return '#2563eb'
}

function utilizationTone(row) {
  if (row.overload > 0 || row.utilization > 100) return '#dc2626'
  if (row.utilization >= 85) return '#f97316'
  if (row.utilization >= 65) return '#eab308'
  return '#16a34a'
}

function revisionLabel(card) {
  if (card.status === 'published') return '正式已发布'
  if (card.status === 'superseded') return '历史已取代'
  if (card.approvalStatus === 'submitted') return '待审批'
  if (card.approvalStatus === 'approved') return '已批准待发布'
  if (card.approvalStatus === 'rejected') return '已驳回'
  return card.candidate ? '草稿（未生效）' : '排程版本'
}

function parsedItem(item) {
  let payload = {}
  try {
    payload = JSON.parse(item.payload_json || '{}')
  } catch {
    payload = {}
  }
  return { ...payload, ...item }
}

const revisionDifferences = computed(() => {
  if (revisionDetail.value?.replan_differences?.length) {
    return revisionDetail.value.replan_differences.map(item => ({
      key: `replan:${item.id || item.order_process_id}`,
      process: `订单工序 #${item.order_process_id}`,
      type: item.change_type || '动态重排',
      before: item.before || {},
      after: item.after || {},
    }))
  }
  const before = new Map((previousRevisionDetail.value?.items || []).map(item => {
    const normalized = parsedItem(item)
    return [String(normalized.order_process_id), normalized]
  }))
  const after = new Map((revisionDetail.value?.items || []).map(item => {
    const normalized = parsedItem(item)
    return [String(normalized.order_process_id), normalized]
  }))
  return [...new Set([...before.keys(), ...after.keys()])].map((key) => {
    const left = before.get(key) || {}
    const right = after.get(key) || {}
    const fields = ['production_node_id', 'planned_start_at', 'planned_end_at', 'quantity', 'occupied_minutes', 'status']
    const changed = fields.filter(field => String(left[field] ?? '') !== String(right[field] ?? ''))
    return {
      key: `compare:${key}`,
      process: right.process_name_snapshot || left.process_name_snapshot || `订单工序 #${key}`,
      type: !left.order_process_id ? '新增' : !right.order_process_id ? '移除' : changed.length ? changed.join('、') : '无变化',
      before: left,
      after: right,
    }
  }).filter(item => item.type !== '无变化')
})

async function loadRevision(revisionId) {
  if (!revisionId) return
  revisionLoading.value = true
  try {
    revisionDetail.value = await api.domains.production.getScheduleRevision(revisionId, { limit: 1000 })
    const revisionNo = Number(revisionDetail.value?.revision?.revision_no || 0)
    const previous = revisionHistory.value.find(item => Number(item.revision_no) < revisionNo)
    previousRevisionDetail.value = previous
      ? await api.domains.production.getScheduleRevision(previous.id, { limit: 1000 })
      : null
  } catch (error) {
    showToast(error.message || '加载排程版本失败', 'error')
  } finally {
    revisionLoading.value = false
  }
}

async function openRevision(card) {
  revisionDialog.value = true
  revisionLoading.value = true
  revisionDetail.value = null
  previousRevisionDetail.value = null
  try {
    const history = await api.domains.production.listOrderScheduleRevisions(card.orderId, { limit: 100 })
    revisionHistory.value = history.revisions || []
    await loadRevision(card.revisionId)
  } catch (error) {
    showToast(error.message || '加载排程版本失败', 'error')
    revisionLoading.value = false
  }
}
</script>

<template>
  <section class="schedule-dashboard" data-test="schedule-capacity-dashboard">
    <header class="schedule-dashboard__header">
      <div>
        <h4>📊 排程与产能驾驶舱</h4>
        <p>看清每个生产节点什么时候做什么、还剩多少产能，以及哪些订单需要优先处理。</p>
      </div>
      <button type="button" class="btn-default btn-sm" @click="$emit('refresh')">刷新看板</button>
    </header>

    <nav class="schedule-dashboard__tabs" aria-label="排程看板">
      <button v-for="tab in [
        { key: 'capacity', label: '分钟甘特图' },
        { key: 'queue', label: '节点排队' },
        { key: 'blocked', label: '阻断任务' },
        { key: 'workbench', label: '风险工作台' },
        { key: 'revisions', label: '版本与差异' },
      ]" :key="tab.key" type="button" :class="{ active: activeWorkbench === tab.key }" @click="activeWorkbench = tab.key">
        {{ tab.label }}
      </button>
    </nav>

    <div v-if="activeWorkbench === 'capacity'" class="schedule-dashboard__body">
      <div v-if="unassignedIntervals.length" class="schedule-dashboard__warning" data-test="unassigned-capacity-warning">
        <strong>有 {{ unassignedIntervals.length }} 个排程时间片尚未绑定稳定生产节点</strong>
        <span>这些任务会显示在甘特图中，但不会冒充任何节点的可用产能；发布前应完成节点分配或重排。</span>
      </div>
      <div class="schedule-dashboard__controls">
        <label>分组
          <select v-model="groupMode" class="form-input" data-test="timeline-group-mode">
            <option value="node">按生产节点</option>
            <option value="process">按工序</option>
            <option value="order">按订单</option>
          </select>
        </label>
        <label>开始日期 <input v-model="anchorDate" type="date" class="form-input"></label>
        <label>时间范围
          <select v-model.number="horizonDays" class="form-input">
            <option :value="7">7 天</option>
            <option :value="14">14 天</option>
            <option :value="30">30 天</option>
          </select>
        </label>
        <span>{{ rangeLabel }} · 精确到分钟</span>
      </div>

      <div class="schedule-dashboard__timeline-scroll">
        <div class="schedule-dashboard__timeline" :style="{ width: timelineWidth + 260 + 'px' }">
          <div class="schedule-dashboard__timeline-header">
            <div class="schedule-dashboard__row-label">生产资源</div>
            <div class="schedule-dashboard__scale" :style="{ width: timelineWidth + 'px' }">
              <span v-for="tick in dayTicks" :key="tick.date" :class="{ weekend: tick.weekend }" :style="{ width: (100 / dayTicks.length) + '%' }">{{ tick.label }}</span>
            </div>
          </div>
          <div v-if="!timelineRows.length" class="schedule-dashboard__empty">当前时间范围内暂无已排任务</div>
          <div v-for="row in timelineRows" :key="row.key" class="schedule-dashboard__timeline-row">
            <div class="schedule-dashboard__row-label" :title="row.label">{{ row.label }}<small>{{ formatMinutes(row.minutes) }}</small></div>
            <div class="schedule-dashboard__track" :style="{ width: timelineWidth + 'px' }">
              <span v-for="tick in dayTicks" :key="`${row.key}:${tick.date}`" class="schedule-dashboard__day-bg" :class="{ weekend: tick.weekend }" :style="{ width: (100 / dayTicks.length) + '%' }"></span>
              <button v-for="bar in row.bars" :key="bar.key" type="button" class="schedule-dashboard__bar" :class="{ candidate: bar.candidate, locked: bar.locked }" :style="{ left: bar.left + '%', width: bar.width + '%', background: barTone(bar) }" :title="`${bar.orderNo} · ${bar.processName} | ${formatDateTime(bar.startAt)} ~ ${formatDateTime(bar.endAt)} | ${formatMinutes(bar.elapsedMinutes)} | 数量 ${bar.quantity}${bar.candidate ? ' | 草稿未生效' : ''}${bar.locked ? ' | 已锁定' : ''}`" @click="emit('filterOrder', bar.orderId)">
                {{ bar.orderNo }} · {{ bar.processName }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="schedule-dashboard__capacity-heading">
        <div><strong>节点产能利用率</strong><span>可用时间已扣除停机，加班作为额外产能计入。</span></div>
        <div class="schedule-dashboard__segmented">
          <button type="button" :class="{ active: capacityPeriod === 'day' }" @click="capacityPeriod = 'day'">按日</button>
          <button type="button" :class="{ active: capacityPeriod === 'week' }" @click="capacityPeriod = 'week'">范围汇总</button>
        </div>
      </div>
      <div class="schedule-dashboard__capacity-grid">
        <button v-for="row in utilizationRows" :key="row.key" type="button" class="schedule-dashboard__capacity-card" @click="emit('filterNode', row.nodeId)">
          <span class="schedule-dashboard__capacity-title"><b>{{ row.label }}</b><small>{{ row.period }}</small></span>
          <span class="schedule-dashboard__meter"><i :style="{ width: Math.min(row.utilization, 100) + '%', background: utilizationTone(row) }"></i></span>
          <span class="schedule-dashboard__capacity-values"><b :style="{ color: utilizationTone(row) }">{{ Math.round(row.utilization) }}%</b><small>占用 {{ formatMinutes(row.occupied) }} / 可用 {{ formatMinutes(row.available) }}</small></span>
          <span class="schedule-dashboard__capacity-foot">剩余 {{ formatMinutes(row.remaining) }}<em v-if="row.downtime">停机 {{ formatMinutes(row.downtime) }}</em><em v-if="row.overtime">加班 +{{ formatMinutes(row.overtime) }}</em><em v-if="row.overload" class="danger">超负荷 {{ formatMinutes(row.overload) }}</em>
          </span>
        </button>
      </div>
    </div>

    <div v-else-if="activeWorkbench === 'workbench'" class="schedule-dashboard__body schedule-dashboard__workbench">
      <article>
        <h5>🔥 瓶颈生产节点 <span>{{ bottleneckRows.length }}</span></h5>
        <p v-if="!bottleneckRows.length" class="schedule-dashboard__empty">暂无高负荷节点</p>
        <button v-for="row in bottleneckRows" :key="`bottleneck:${row.key}`" type="button" @click="emit('filterNode', row.nodeId)">
          <b>{{ row.label }}</b><span :style="{ color: utilizationTone(row) }">{{ Math.round(row.utilization) }}%</span><small>{{ row.period }} · 剩余 {{ formatMinutes(row.remaining) }}<template v-if="row.overload"> · 超载 {{ formatMinutes(row.overload) }}</template></small>
        </button>
      </article>
      <article>
        <h5>⚠️ 交期风险订单 <span>{{ riskOrders.length }}</span></h5>
        <p v-if="!riskOrders.length" class="schedule-dashboard__empty">暂无高风险订单</p>
        <button v-for="order in riskOrders.slice(0, 10)" :key="`risk:${order.order_id}`" type="button" @click="emit('filterOrder', order.order_id)">
          <b>{{ order.order_no }}</b><span class="danger">{{ order.risk_level === 'overdue' ? '已逾期' : '高风险' }}</span><small>{{ order.risk_reason || '需要排程人员复核' }}<template v-if="order.delay_minutes"> · 延期 {{ formatMinutes(order.delay_minutes) }}</template></small>
        </button>
      </article>
      <article>
        <h5>🔄 待动态重排 <span>{{ pendingReplanOrders.length }}</span></h5>
        <p v-if="!pendingReplanOrders.length" class="schedule-dashboard__empty">没有待重排订单</p>
        <button v-for="order in pendingReplanOrders.slice(0, 10)" :key="`replan:${order.id}`" type="button" @click="emit('filterOrder', order.id)">
          <b>{{ order.order_no }}</b><span>待重排</span><small>{{ order.schedule_replan_reason || '报工、停机或返工事实已变化' }}</small>
        </button>
      </article>
      <article>
        <h5>🔒 人工锁定任务 <span>{{ lockedTasks.length }}</span></h5>
        <p v-if="!lockedTasks.length" class="schedule-dashboard__empty">没有人工锁定任务</p>
        <button v-for="task in lockedTasks.slice(0, 10)" :key="`lock:${task.revision_item_id || task.id}`" type="button" @click="emit('filterOrder', task.order_id)">
          <b>{{ task.order_no }}</b><span>已锁定</span><small>{{ task.process_name }} · {{ task.node_code || task.node_name || '未分配节点' }}</small>
        </button>
      </article>
    </div>

    <div v-else-if="activeWorkbench === 'queue'" class="schedule-dashboard__body">
      <ProductionNodeQueueBoard
        :operations="operations"
        :nodes="nodes"
        :orders="orders"
        @open-order="emit('openOrder', $event)"
        @filter-node="emit('filterNode', $event)"
      />
    </div>

    <div v-else-if="activeWorkbench === 'blocked'" class="schedule-dashboard__body">
      <div class="schedule-blocked-center" data-test="schedule-blocked-center">
        <header><div><h5>阻断任务中心</h5><p>每条阻断都必须说明原因和下一步处理入口，不能只显示服务器错误。</p></div><span>{{ blockedOperations.length }} 条</span></header>
        <div v-if="!blockedOperations.length" class="schedule-dashboard__empty">当前没有阻断任务</div>
        <article v-for="operation in blockedOperations" :key="operation.id || operation.order_process_id" class="schedule-blocked-item">
          <div><strong>{{ operation.order_no || `订单 #${operation.order_id}` }}</strong><span>{{ operation.process_name || `工序 #${operation.process_id}` }}</span></div>
          <p>{{ operation.blocked_reason || operation.reason || operation.error_message || '前置条件不满足' }}</p>
          <div class="schedule-blocked-item__actions">
            <button type="button" class="btn-default btn-sm" @click="emit('openOrder', orders.find(order => String(order.id) === String(operation.order_id)) || { id: operation.order_id, order_no: operation.order_no })">查看订单详情</button>
            <button type="button" class="btn-default btn-sm" @click="emit('filterNode', operation.production_node_id)">查看节点</button>
            <button type="button" class="btn-default btn-sm" @click="emit('filterOrder', operation.order_id)">重新试排</button>
          </div>
        </article>
      </div>
    </div>

    <div v-else class="schedule-dashboard__body">
      <div class="schedule-dashboard__revision-help">
        <strong>排程版本不会自动覆盖生产执行</strong>
        <span>草稿、待审批和已批准版本只有发布后才生效；点击“查看差异”可与上一版对比。</span>
      </div>
      <div class="schedule-dashboard__revision-grid">
        <article v-for="card in revisionCards" :key="card.key">
          <div><strong>{{ card.orderNo }}</strong><span>#{{ card.revisionId }}</span></div>
          <b :class="{ candidate: card.candidate }">{{ revisionLabel(card) }}</b>
          <p>{{ card.operationCount }} 道工序 · {{ card.lockedCount }} 道锁定 · {{ card.conflictCount }} 处冲突</p>
          <button type="button" class="btn-default btn-sm" @click="openRevision(card)">查看版本与差异</button>
        </article>
        <p v-if="!revisionCards.length" class="schedule-dashboard__empty">当前没有可查看的排程版本</p>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="revisionDialog" class="schedule-revision-dialog__overlay">
        <section class="schedule-revision-dialog" role="dialog" aria-modal="true" aria-labelledby="schedule-revision-dialog-title">
          <header>
            <div><h3 id="schedule-revision-dialog-title">排程版本与差异</h3><p>对比当前选中版本与上一个版本，便于审批前复核节点、时间、数量和风险变化。</p></div>
            <button type="button" class="btn-default" @click="revisionDialog = false">关闭</button>
          </header>
          <div class="schedule-revision-dialog__toolbar">
            <label>排程版本
              <select class="form-input" :value="revisionDetail?.revision?.id || ''" @change="loadRevision($event.target.value)">
                <option v-for="revision in revisionHistory" :key="revision.id" :value="revision.id">第 {{ revision.revision_no }} 版 · {{ revision.status }} / {{ revision.approval_status }}</option>
              </select>
            </label>
            <span v-if="revisionDetail?.revision">风险 {{ revisionDetail.revision.risk_level || '未评估' }} · 延期 {{ formatMinutes(revisionDetail.revision.delay_minutes) }}</span>
          </div>
          <div v-if="revisionLoading" class="schedule-dashboard__empty">正在加载排程版本…</div>
          <div v-else class="schedule-revision-dialog__content">
            <div class="schedule-revision-dialog__summary">
              <span>工序 {{ revisionDetail?.items?.length || 0 }}</span>
              <span>阻断冲突 {{ revisionDetail?.conflict_summary?.blocking_count || 0 }}</span>
              <span>变化 {{ revisionDifferences.length }}</span>
              <span v-if="revisionDetail?.replan_summary">动态重排：{{ revisionDetail.replan_summary.reason || revisionDetail.replan_summary.trigger_reason || '生产事实变化' }}</span>
            </div>
            <div v-if="revisionDifferences.length" class="schedule-revision-dialog__diffs">
              <article v-for="difference in revisionDifferences" :key="difference.key">
                <header><b>{{ difference.process }}</b><span>{{ difference.type }}</span></header>
                <div><small>上一版</small><span>节点 {{ difference.before.production_node_id || '-' }} · {{ formatDateTime(difference.before.planned_start_at) }} ~ {{ formatDateTime(difference.before.planned_end_at) }} · {{ difference.before.quantity || 0 }} 件</span></div>
                <div><small>当前版</small><span>节点 {{ difference.after.production_node_id || '-' }} · {{ formatDateTime(difference.after.planned_start_at) }} ~ {{ formatDateTime(difference.after.planned_end_at) }} · {{ difference.after.quantity || 0 }} 件</span></div>
              </article>
            </div>
            <p v-else class="schedule-dashboard__empty">与上一版相比没有可见的排程差异</p>
          </div>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.schedule-dashboard { margin:0 0 16px; border:1px solid var(--border-light); border-radius:var(--radius-lg); background:var(--bg-surface); overflow:hidden; }
.schedule-dashboard__header { display:flex; align-items:center; gap:16px; justify-content:space-between; padding:14px 16px; background:linear-gradient(120deg,#eff6ff,#f0fdfa); border-bottom:1px solid var(--border-light); }
.schedule-dashboard__header h4 { margin:0; font-size:var(--text-base); }
.schedule-dashboard__header p { margin:4px 0 0; color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-dashboard__tabs { display:flex; gap:4px; padding:8px 12px 0; border-bottom:1px solid var(--border-light); overflow:auto; }
.schedule-dashboard__tabs button { border:0; background:transparent; padding:8px 14px; white-space:nowrap; color:var(--text-secondary); cursor:pointer; border-bottom:2px solid transparent; }
.schedule-dashboard__tabs button.active { color:var(--primary); border-bottom-color:var(--primary); font-weight:700; }
.schedule-dashboard__body { padding:14px; }
.schedule-dashboard__warning { display:flex; flex-direction:column; gap:3px; margin-bottom:10px; padding:9px 11px; border:1px solid #fdba74; border-radius:var(--radius-sm); background:#fff7ed; color:#9a3412; font-size:var(--text-xs); }
.schedule-dashboard__controls { display:flex; align-items:end; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
.schedule-dashboard__controls label { display:flex; flex-direction:column; gap:4px; font-size:var(--text-xs); color:var(--text-secondary); }
.schedule-dashboard__controls .form-input { min-width:130px; padding:5px 8px; font-size:var(--text-xs); }
.schedule-dashboard__controls > span { margin-left:auto; color:var(--text-placeholder); font-size:var(--text-xs); }
.schedule-dashboard__timeline-scroll { overflow:auto; border:1px solid var(--border-light); border-radius:var(--radius-sm); }
.schedule-dashboard__timeline { min-width:100%; }
.schedule-dashboard__timeline-header,.schedule-dashboard__timeline-row { display:flex; min-height:46px; border-bottom:1px solid var(--bg-hover); }
.schedule-dashboard__timeline-header { position:sticky; top:0; z-index:3; background:var(--bg-surface); min-height:34px; }
.schedule-dashboard__row-label { position:sticky; left:0; z-index:2; display:flex; flex-direction:column; justify-content:center; width:260px; min-width:260px; padding:6px 10px; background:var(--bg-surface); border-right:1px solid var(--border-light); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:var(--text-xs); font-weight:600; }
.schedule-dashboard__row-label small { color:var(--text-placeholder); font-weight:400; }
.schedule-dashboard__scale { display:flex; }
.schedule-dashboard__scale span { padding:8px 2px; text-align:center; border-right:1px solid var(--border-light); color:var(--text-placeholder); font-size:10px; }
.schedule-dashboard__scale span.weekend,.schedule-dashboard__day-bg.weekend { background:rgba(148,163,184,.14); }
.schedule-dashboard__track { position:relative; display:flex; overflow:hidden; }
.schedule-dashboard__day-bg { height:100%; border-right:1px solid var(--border-light); }
.schedule-dashboard__bar { position:absolute; top:10px; z-index:1; height:26px; min-width:4px; overflow:hidden; border:0; border-radius:4px; padding:0 5px; color:#fff; text-overflow:ellipsis; white-space:nowrap; font-size:10px; cursor:pointer; box-shadow:0 1px 3px rgba(15,23,42,.24); }
.schedule-dashboard__bar.candidate { border:2px dashed #fff; }
.schedule-dashboard__bar.locked::after { content:' 🔒'; }
.schedule-blocked-center { display:grid; gap:10px; }
.schedule-blocked-center > header { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; padding:12px 14px; border:1px solid #fecaca; border-radius:var(--radius-sm); background:#fff7f7; }
.schedule-blocked-center h5 { margin:0; font-size:var(--text-sm); color:var(--danger); }
.schedule-blocked-center header p { margin:4px 0 0; color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-blocked-item { display:grid; gap:7px; padding:12px 14px; border:1px solid #fecaca; border-radius:var(--radius-sm); background:var(--bg-surface); }
.schedule-blocked-item > div:first-child { display:flex; gap:10px; align-items:center; }
.schedule-blocked-item > div:first-child span { color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-blocked-item p { margin:0; color:var(--danger); font-size:var(--text-sm); }
.schedule-blocked-item__actions { display:flex; gap:8px; flex-wrap:wrap; }
.schedule-dashboard__capacity-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:16px 0 10px; }
.schedule-dashboard__capacity-heading > div:first-child { display:flex; flex-direction:column; }
.schedule-dashboard__capacity-heading span { color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-dashboard__segmented { display:flex; padding:2px; background:var(--bg-hover); border-radius:999px; }
.schedule-dashboard__segmented button { border:0; background:transparent; padding:4px 10px; border-radius:999px; font-size:var(--text-xs); cursor:pointer; }
.schedule-dashboard__segmented button.active { background:var(--primary); color:#fff; }
.schedule-dashboard__capacity-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:8px; max-height:360px; overflow:auto; }
.schedule-dashboard__capacity-card { display:flex; flex-direction:column; gap:6px; padding:10px; text-align:left; border:1px solid var(--border-light); border-radius:var(--radius-sm); background:#fff; cursor:pointer; }
.schedule-dashboard__capacity-card:hover { border-color:var(--primary); }
.schedule-dashboard__capacity-title,.schedule-dashboard__capacity-values,.schedule-dashboard__capacity-foot { display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:var(--text-xs); }
.schedule-dashboard__capacity-title small,.schedule-dashboard__capacity-values small { color:var(--text-secondary); }
.schedule-dashboard__meter { display:block; height:7px; background:var(--bg-hover); border-radius:999px; overflow:hidden; }
.schedule-dashboard__meter i { display:block; height:100%; border-radius:999px; }
.schedule-dashboard__capacity-foot { color:var(--text-secondary); justify-content:flex-start; flex-wrap:wrap; }
.schedule-dashboard__capacity-foot em { font-style:normal; color:#a16207; }
.schedule-dashboard .danger { color:var(--danger)!important; }
.schedule-dashboard__workbench { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.schedule-dashboard__workbench article { border:1px solid var(--border-light); border-radius:var(--radius-sm); padding:10px; min-height:140px; }
.schedule-dashboard__workbench h5 { display:flex; justify-content:space-between; margin:0 0 8px; }
.schedule-dashboard__workbench article > button { display:grid; grid-template-columns:1fr auto; gap:2px 8px; width:100%; padding:7px 4px; text-align:left; border:0; border-top:1px solid var(--bg-hover); background:transparent; cursor:pointer; font-size:var(--text-xs); }
.schedule-dashboard__workbench article > button small { grid-column:1 / -1; overflow:hidden; color:var(--text-secondary); text-overflow:ellipsis; white-space:nowrap; }
.schedule-dashboard__revision-help { display:flex; flex-direction:column; gap:3px; margin-bottom:10px; padding:10px 12px; background:#fffbeb; border:1px solid #fde68a; border-radius:var(--radius-sm); color:#92400e; font-size:var(--text-xs); }
.schedule-dashboard__revision-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:8px; }
.schedule-dashboard__revision-grid article { padding:10px; border:1px solid var(--border-light); border-radius:var(--radius-sm); }
.schedule-dashboard__revision-grid article > div { display:flex; justify-content:space-between; }
.schedule-dashboard__revision-grid article > b { display:block; margin-top:8px; color:var(--success); font-size:var(--text-sm); }
.schedule-dashboard__revision-grid article > b.candidate { color:#b45309; }
.schedule-dashboard__revision-grid p { margin:5px 0 9px; color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-dashboard__empty { padding:18px; text-align:center; color:var(--text-placeholder); font-size:var(--text-xs); }
.schedule-revision-dialog__overlay { position:fixed; inset:0; z-index:1100; display:flex; justify-content:flex-end; background:rgba(15,23,42,.52); }
.schedule-revision-dialog { display:flex; flex-direction:column; width:min(860px,96vw); height:100%; background:var(--bg-surface); box-shadow:-20px 0 60px rgba(15,23,42,.32); overflow:hidden; }
.schedule-revision-dialog > header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding:16px 18px; border-bottom:1px solid var(--border-light); }
.schedule-revision-dialog h3,.schedule-revision-dialog p { margin:0; }
.schedule-revision-dialog header p { margin-top:4px; color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-revision-dialog__toolbar { display:flex; align-items:end; gap:14px; padding:10px 18px; background:var(--bg-hover); font-size:var(--text-xs); }
.schedule-revision-dialog__toolbar label { display:flex; flex-direction:column; gap:4px; }
.schedule-revision-dialog__toolbar select { min-width:260px; }
.schedule-revision-dialog__content { padding:14px 18px 18px; overflow:auto; }
.schedule-revision-dialog__summary { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
.schedule-revision-dialog__summary span { padding:5px 8px; border-radius:999px; background:var(--primary-light); color:var(--primary); font-size:var(--text-xs); }
.schedule-revision-dialog__diffs { display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:8px; }
.schedule-revision-dialog__diffs article { border:1px solid var(--border-light); border-radius:var(--radius-sm); overflow:hidden; }
.schedule-revision-dialog__diffs article header { display:flex; justify-content:space-between; gap:8px; padding:8px 10px; background:var(--bg-hover); font-size:var(--text-xs); }
.schedule-revision-dialog__diffs article > div { display:grid; grid-template-columns:60px 1fr; gap:8px; padding:7px 10px; border-top:1px solid var(--bg-hover); font-size:var(--text-xs); }
.schedule-revision-dialog__diffs small { color:var(--text-placeholder); }
@media (max-width:899px) {
  .schedule-dashboard__header,.schedule-dashboard__capacity-heading { align-items:flex-start; flex-direction:column; }
  .schedule-dashboard__controls > span { width:100%; margin-left:0; }
  .schedule-dashboard__workbench { grid-template-columns:1fr; }
  .schedule-dashboard__capacity-grid { grid-template-columns:1fr; max-height:none; }
  .schedule-revision-dialog__overlay { padding:0; }
  .schedule-revision-dialog { width:100%; height:100%; max-height:none; border-radius:0; }
  .schedule-revision-dialog__toolbar { align-items:stretch; flex-direction:column; }
  .schedule-revision-dialog__toolbar select { width:100%; min-width:0; }
}
</style>
