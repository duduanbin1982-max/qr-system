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

export function useGanttData({ productionLines }) {
  const orders = ref([])
  const loading = ref(true)
  const dayWidth = ref(38)
  const scheduleScope = ref('active')
  const wsFilter = ref('')
  const serverStats = ref({ total: 0, producing: 0, pending: 0, completed: 0 })
  const dateRange = ref({ minDate: '', maxDate: '' })

  const stats = computed(() => serverStats.value)
  const filteredOrders = computed(() => {
    if (!wsFilter.value) return orders.value
    return orders.value.filter(
      order => String(order.production_line_id || '') === String(wsFilter.value),
    )
  })
  const ganttData = computed(() => buildGanttData(filteredOrders.value, dateRange.value))
  const dailyLoad = computed(() => calculateDailyLoad(
    filteredOrders.value,
    productionLines.value,
  ))
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

  function isOverloaded(date, lineId) {
    if (!lineId || !date) return false
    return dailyLoad.value.some(
      load => load.date === date && String(load.lineId) === String(lineId),
    )
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

  return {
    orders,
    stats,
    loading,
    dayWidth,
    scheduleScope,
    wsFilter,
    filteredOrders,
    ganttData,
    dailyLoad,
    riskSummary,
    barLeft,
    barWidth,
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
    isOverloaded,
    load,
    setScheduleScope,
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

function calculateDailyLoad(orders, productionLines) {
  const loadMap = {}
  orders.forEach((order) => {
    if (!order.plan_start || !order.plan_end || !order.production_line_id) return
    const end = new Date(order.plan_end)
    for (let date = new Date(order.plan_start); date <= end; date.setDate(date.getDate() + 1)) {
      const dateValue = date.toISOString().slice(0, 10)
      const key = `${dateValue}|${order.production_line_id}`
      if (!loadMap[key]) {
        loadMap[key] = {
          date: dateValue,
          lineId: order.production_line_id,
          line: order.production_line,
          count: 0,
          capacity: Number(order.line_capacity) > 0 ? Number(order.line_capacity) : 999,
        }
      }
      loadMap[key].count++
    }
  })
  productionLines.forEach((line) => {
    Object.values(loadMap).forEach((load) => {
      if (
        String(load.lineId) === String(line.id)
        && Number(line.capacity_per_day) > 0
      ) {
        load.capacity = Number(line.capacity_per_day)
      }
    })
  })
  return Object.values(loadMap).filter(load => load.count > load.capacity)
}
