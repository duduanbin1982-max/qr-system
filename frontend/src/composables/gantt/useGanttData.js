import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const RISK_LABELS = Object.freeze({
  none: '正常',
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  overdue: '已逾期',
})

const RISK_COLORS = Object.freeze({
  none: 'var(--success)',
  low: '#65a30d',
  medium: 'var(--warning)',
  high: '#f97316',
  overdue: 'var(--danger)',
})

const SAVED_FILTERS_STORAGE_KEY = 'schedule-gantt-saved-filters-v1'


export function isCompletedOrder(order) {
  if (!order) return false
  const quantity = order.quantity || 0
  const completed = order.completed_qty || order.completed || 0
  return Boolean(
    order.is_completed
    || order.status === 'completed'
    || (quantity > 0 && completed >= quantity)
  )
}

export function useGanttData() {
  const orders = ref([])
  const loading = ref(true)
  const dayWidth = ref(38)
  const scheduleScope = ref('active')
  const riskFilter = ref('all')
  const orderKeyword = ref('')
  const productKeyword = ref('')
  const priorityFilter = ref('all')
  const statusFilter = ref('all')
  const deadlineFrom = ref('')
  const deadlineTo = ref('')
  const lockedFilter = ref('all')
  const savedFilters = ref(loadSavedFilters())
  const serverStats = ref({ total: 0, producing: 0, pending: 0, completed: 0 })
  const dateRange = ref({ minDate: '', maxDate: '' })

  const stats = computed(() => serverStats.value)
  const filteredOrders = computed(() => orders.value.filter((order) => {
    const keyword = String(orderKeyword.value || '').trim().toLowerCase()
    if (keyword && ![order.order_no, order.id].some(value => String(value ?? '').toLowerCase().includes(keyword))) return false
    const productKeywordValue = String(productKeyword.value || '').trim().toLowerCase()
    if (productKeywordValue && ![order.product_code, order.product_name].some(value => String(value ?? '').toLowerCase().includes(productKeywordValue))) return false
    if (priorityFilter.value !== 'all') {
      const rawPriority = String(order.priority_level ?? order.priority ?? '')
      const selectedPriority = String(priorityFilter.value).replace(/^P/i, '')
      if (rawPriority !== selectedPriority) return false
    }
    if (statusFilter.value !== 'all' && String(order.status || '') !== String(statusFilter.value)) return false
    const deadline = String(order.deadline || order.deadline_at || '').slice(0, 10)
    if (deadlineFrom.value && (!deadline || deadline < deadlineFrom.value)) return false
    if (deadlineTo.value && (!deadline || deadline > deadlineTo.value)) return false
    if (lockedFilter.value !== 'all') {
      const locked = Boolean(order.locked || order.is_locked || Number(order.locked_task_count || 0) > 0)
      if (lockedFilter.value === 'locked' && !locked) return false
      if (lockedFilter.value === 'unlocked' && locked) return false
    }
    if (riskFilter.value === 'all') return true
    if (riskFilter.value === 'critical') {
      return ['overdue', 'high'].includes(riskLevel(order))
    }
    if (riskFilter.value === 'conflict') {
      return Number(order.schedule_conflict_count || 0) > 0
    }
    if (riskFilter.value === 'blocked') {
      return Number(order.schedule_blocked_count || 0) > 0
    }
    return riskLevel(order) === riskFilter.value
  }))
  const ganttData = computed(() => buildGanttData(filteredOrders.value, dateRange.value))
  const riskSummary = computed(() => {
    const summary = {
      overdue: 0,
      high: 0,
      medium: 0,
      low: 0,
      none: 0,
      delayed: 0,
      totalDelayMinutes: 0,
    }
    filteredOrders.value.forEach((order) => {
      const level = riskLevel(order)
      summary[level] = (summary[level] || 0) + 1
      const delay = Math.max(Number(order.delay_minutes) || 0, 0)
      if (delay > 0) summary.delayed += 1
      summary.totalDelayMinutes += delay
    })
    return summary
  })

  function barLeft(order) {
    const min = ganttData.value.minDate
    if (!min || !order.plan_start) return 0
    return Math.max(0, (new Date(order.plan_start) - new Date(min)) / 86400000) * dayWidth.value
  }

  function barWidth(order) {
    if (!order.plan_start || !order.plan_end) return dayWidth.value
    const days = Math.max(
      1,
      (new Date(order.plan_end) - new Date(order.plan_start)) / 86400000 + 1,
    )
    return days * dayWidth.value
  }

  function actualBarLeft(order) {
    const min = ganttData.value.minDate
    const startValue = order.actual_start_at || order.actual_start
    if (!min || !startValue) return 0
    return Math.max(0, (new Date(startValue) - new Date(min)) / 86400000) * dayWidth.value
  }

  function actualBarWidth(order) {
    const startValue = order.actual_start_at || order.actual_start
    const endValue = order.actual_end_at || order.actual_end || startValue
    if (!startValue || !endValue) return 4
    const days = Math.max(1 / 24, (new Date(endValue) - new Date(startValue)) / 86400000)
    return Math.max(4, days * dayWidth.value)
  }

  function barColor(status) {
    if (status === 'producing') return 'linear-gradient(135deg,#2563eb,#3b82f6)'
    if (status === 'completed') return 'linear-gradient(135deg,#16a34a,#22c55e)'
    return 'linear-gradient(135deg,#9ca3af,#b0b7c3)'
  }

  function statusLabel(status) {
    return { producing: '生产中', pending: '待生产', completed: '已完成' }[status] || status
  }

  function riskLevel(order) {
    const level = String(order?.risk_level || '').trim()
    if (Object.prototype.hasOwnProperty.call(RISK_LABELS, level)) return level
    if (order?.risk === 'overdue') return 'overdue'
    if (order?.risk === 'warning') return 'medium'
    return 'none'
  }

  function riskLabel(orderOrLevel) {
    const level = typeof orderOrLevel === 'string'
      ? orderOrLevel
      : riskLevel(orderOrLevel)
    return RISK_LABELS[level] || level || '正常'
  }

  function riskColor(orderOrLevel) {
    const level = typeof orderOrLevel === 'string'
      ? orderOrLevel
      : riskLevel(orderOrLevel)
    return RISK_COLORS[level] || RISK_COLORS.none
  }

  function riskIcon(orderOrLevel) {
    const level = typeof orderOrLevel === 'string'
      ? orderOrLevel
      : riskLevel(orderOrLevel)
    return { overdue: '⛔', high: '🔴', medium: '🟠', low: '🟡', none: '🟢' }[level] || '🟢'
  }

  function formatRiskMinutes(value) {
    const minutes = Math.max(Math.round(Number(value) || 0), 0)
    if (minutes < 60) return `${minutes} 分钟`
    const days = Math.floor(minutes / 1440)
    const hours = Math.floor((minutes % 1440) / 60)
    const remainder = minutes % 60
    return [days ? `${days} 天` : '', hours ? `${hours} 小时` : '', remainder ? `${remainder} 分钟` : '']
      .filter(Boolean)
      .join(' ')
  }

  function riskTooltip(order) {
    const parts = [
      `交期风险：${riskLabel(order)}`,
      order?.risk_reason || '',
      order?.deadline_at ? `交期：${order.deadline_at}` : '',
      order?.projected_completion_at ? `预计完成：${order.projected_completion_at}` : '',
      Number(order?.delay_minutes) > 0 ? `预计延期：${formatRiskMinutes(order.delay_minutes)}` : '',
      Number(order?.slack_minutes) >= 0 ? `剩余缓冲：${formatRiskMinutes(order.slack_minutes)}` : '',
      Number(order?.schedule_conflict_count) > 0 ? `生产节点冲突：${order.schedule_conflict_count} 处` : '',
      ...(order?.risk_suggested_actions || []).map(action => `建议：${action}`),
    ]
    return parts.filter(Boolean).join(' | ')
  }

  function riskBarShadow(order, overloaded = false) {
    const level = riskLevel(order)
    if (level === 'overdue' || level === 'high') {
      return `0 0 0 2px ${riskColor(level)}, 0 2px 8px rgba(220,38,38,0.35)`
    }
    if (level === 'medium' || level === 'low') {
      return `0 0 0 2px ${riskColor(level)}, 0 1px 5px rgba(245,158,11,0.28)`
    }
    if (overloaded) return '0 0 0 2px var(--danger), 0 1px 3px rgba(0,0,0,0.3)'
    return '0 1px 3px rgba(0,0,0,0.15)'
  }

  function zoomIn() {
    dayWidth.value = Math.min(dayWidth.value + 6, 80)
  }

  function zoomOut() {
    dayWidth.value = Math.max(dayWidth.value - 6, 20)
  }

  async function load() {
    loading.value = true
    try {
      const pageSize = 200
      let offset = 0
      let hasMore = true
      let loadedOrders = []
      while (hasMore) {
        const response = await api.domains.production.getScheduleGantt({
          status: scheduleScope.value,
          limit: pageSize,
          offset,
        })
        if (response.ok === false) throw new Error(response.error || '加载排程失败')
        const pageOrders = response.orders || []
        loadedOrders = loadedOrders.concat(pageOrders)
        if (offset === 0) applyFirstPageMetadata(response, pageOrders)
        offset = loadedOrders.length
        hasMore = Boolean(response.has_more) && pageOrders.length > 0
      }
      orders.value = loadedOrders
    } catch (error) {
      showToast(error.message || '加载排程失败', 'error')
    } finally {
      loading.value = false
    }
  }

  function applyFirstPageMetadata(response, pageOrders) {
    dateRange.value = {
      minDate: response.min_date || '',
      maxDate: response.max_date || '',
    }
    serverStats.value = response.stats || {
      total: response.total || pageOrders.length,
      producing: pageOrders.filter(
        order => order.status === 'producing' && !isCompletedOrder(order),
      ).length,
      pending: pageOrders.filter(
        order => order.status === 'pending' && !isCompletedOrder(order),
      ).length,
      completed: pageOrders.filter(isCompletedOrder).length,
    }
  }

  async function setScheduleScope(scope) {
    if (scheduleScope.value === scope) return
    scheduleScope.value = scope
    await load()
  }

  function currentFilterSnapshot() {
    return {
      orderKeyword: orderKeyword.value,
      productKeyword: productKeyword.value,
      priorityFilter: priorityFilter.value,
      statusFilter: statusFilter.value,
      deadlineFrom: deadlineFrom.value,
      deadlineTo: deadlineTo.value,
      riskFilter: riskFilter.value,
      lockedFilter: lockedFilter.value,
    }
  }

  function applyFilterSnapshot(snapshot = {}) {
    orderKeyword.value = snapshot.orderKeyword || ''
    productKeyword.value = snapshot.productKeyword || ''
    priorityFilter.value = snapshot.priorityFilter || 'all'
    statusFilter.value = snapshot.statusFilter || 'all'
    deadlineFrom.value = snapshot.deadlineFrom || ''
    deadlineTo.value = snapshot.deadlineTo || ''
    riskFilter.value = snapshot.riskFilter || 'all'
    lockedFilter.value = snapshot.lockedFilter || 'all'
  }

  function resetFilters() {
    applyFilterSnapshot()
  }

  function saveFilter(name) {
    const label = String(name || '').trim()
    if (!label) return false
    const next = savedFilters.value.filter(item => item.name !== label)
    next.unshift({ name: label, filters: currentFilterSnapshot(), updatedAt: new Date().toISOString() })
    savedFilters.value = next.slice(0, 20)
    persistSavedFilters(savedFilters.value)
    return true
  }

  function applySavedFilter(name) {
    const item = savedFilters.value.find(filter => filter.name === name)
    if (!item) return false
    applyFilterSnapshot(item.filters)
    return true
  }

  function deleteSavedFilter(name) {
    savedFilters.value = savedFilters.value.filter(item => item.name !== name)
    persistSavedFilters(savedFilters.value)
  }

  return {
    orders,
    stats,
    loading,
    dayWidth,
    scheduleScope,
    riskFilter,
    orderKeyword,
    productKeyword,
    priorityFilter,
    statusFilter,
    deadlineFrom,
    deadlineTo,
    lockedFilter,
    savedFilters,
    filteredOrders,
    ganttData,
    riskSummary,
    barLeft,
    barWidth,
    actualBarLeft,
    actualBarWidth,
    barColor,
    statusLabel,
    riskLevel,
    riskLabel,
    riskColor,
    riskIcon,
    formatRiskMinutes,
    riskTooltip,
    riskBarShadow,
    zoomIn,
    zoomOut,
    load,
    setScheduleScope,
    currentFilterSnapshot,
    applyFilterSnapshot,
    resetFilters,
    saveFilter,
    applySavedFilter,
    deleteSavedFilter,
  }
}

function loadSavedFilters() {
  if (typeof localStorage === 'undefined') return []
  try {
    const value = JSON.parse(localStorage.getItem(SAVED_FILTERS_STORAGE_KEY) || '[]')
    return Array.isArray(value) ? value.filter(item => item && item.name && item.filters) : []
  } catch {
    return []
  }
}

function persistSavedFilters(filters) {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(SAVED_FILTERS_STORAGE_KEY, JSON.stringify(filters))
  } catch {
    // 本地存储不可用时筛选仍可正常使用，只是不持久化保存方案。
  }
}

function buildGanttData(orders, range) {
  if (!orders.length || !range.minDate || !range.maxDate) {
    return { minDate: '', maxDate: '', totalDays: 0, days: [] }
  }
  const start = new Date(range.minDate)
  const end = new Date(range.maxDate)
  const totalDays = Math.max(Math.ceil((end - start) / 86400000) + 1, 1)
  const days = Array.from({ length: totalDays }, (_, index) => {
    const date = new Date(start)
    date.setDate(date.getDate() + index)
    return {
      date: date.toISOString().slice(0, 10),
      label: `${date.getMonth() + 1}/${date.getDate()}`,
      isToday: date.toDateString() === new Date().toDateString(),
      isWeekend: date.getDay() === 0 || date.getDay() === 6,
    }
  })
  return {
    minDate: range.minDate,
    maxDate: range.maxDate,
    totalDays,
    days,
  }
}
