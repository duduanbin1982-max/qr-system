import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const STANDARD_SCOPE_LABELS = Object.freeze({
  'route_version:product': '路线版本 · 产品专用',
  'route:product': '路线 · 产品专用',
  'process:product': '工序 · 产品专用',
  'route_version:generic': '路线版本 · 通用',
  'route:generic': '路线 · 通用',
  'process:generic': '工序 · 通用',
})


export function useGanttCapacity({ orders }) {
  const viewMode = ref('orders')
  const capacityLines = ref([])
  const operationSchedules = ref([])
  const capacityOrders = ref([])
  const capacityLoading = ref(false)
  const capacityProcessFilter = ref('')
  const capacityLineFilter = ref('')
  const generationOrderId = ref('')
  const generationStartDate = ref('')
  const generationRunKey = ref('')

  const processOptions = computed(() => {
    const seen = new Map()
    capacityLines.value.forEach((line) => {
      if (!seen.has(line.process_id)) seen.set(line.process_id, line.process_name)
    })
    operationSchedules.value.forEach((row) => {
      if (!seen.has(row.process_id)) seen.set(row.process_id, row.process_name)
    })
    return [...seen.entries()].map(([id, name]) => ({ id, name }))
  })

  const filteredOperations = computed(() => operationSchedules.value.filter((row) => {
    if (capacityProcessFilter.value && String(row.process_id) !== String(capacityProcessFilter.value)) return false
    if (capacityLineFilter.value && String(row.process_line_id || '') !== String(capacityLineFilter.value)) return false
    return true
  }))

  const capacitySummary = computed(() => {
    const rows = filteredOperations.value
    return {
      total: rows.length,
      planned: rows.filter(row => row.schedule_status === 'planned' || row.status === 'planned').length,
      blocked: rows.filter(row => row.schedule_status === 'blocked' || row.status === 'blocked').length,
      minutes: rows.reduce((sum, row) => sum + Number(row.occupied_minutes ?? row.planned_minutes ?? 0), 0),
    }
  })

  async function loadCapacity() {
    capacityLoading.value = true
    try {
      const [lineData, scheduleData, orderData] = await Promise.all([
        api.domains.production.listProcessCapacityLines(),
        api.domains.production.listOperationSchedules({ limit: 1000 }),
        api.domains.production.listCapacityOrders({ limit: 1000 }),
      ])
      capacityLines.value = lineData.lines || []
      operationSchedules.value = scheduleData.operations || []
      capacityOrders.value = orderData.orders || orders.value || []
    } catch (error) {
      showToast(error.message || '加载工序排程失败', 'error')
      capacityLines.value = []
      operationSchedules.value = []
    } finally {
      capacityLoading.value = false
    }
  }

  async function setViewMode(mode) {
    viewMode.value = mode
    if (mode === 'operations' && !operationSchedules.value.length && !capacityLoading.value) {
      await loadCapacity()
    }
  }

  function startGeneration(order) {
    generationOrderId.value = order?.id || ''
    generationStartDate.value = order?.plan_start || new Date().toISOString().slice(0, 10)
    generationRunKey.value = `schedule-${order?.id || 'order'}-${Date.now()}`
  }

  function prepareGeneration(orderId) {
    const order = capacityOrders.value.find(item => String(item.id) === String(orderId))
      || orders.value.find(item => String(item.id) === String(orderId))
    if (order) startGeneration(order)
  }

  async function generateSchedule() {
    if (!generationOrderId.value) {
      showToast('请选择订单', 'error')
      return
    }
    try {
      await api.domains.production.generateOrderOperationSchedule(generationOrderId.value, {
        start_date: generationStartDate.value,
        schedule_run_key: generationRunKey.value,
      })
      showToast('工序排程已生成')
      await loadCapacity()
    } catch (error) {
      showToast(error.message || '生成工序排程失败', 'error')
    }
  }

  function lineLabel(row) {
    return row.line_name || (row.process_line_id ? `产线 #${row.process_line_id}` : '未分配')
  }

  function standardScopeLabel(scope) {
    const value = String(scope || '').trim()
    return STANDARD_SCOPE_LABELS[value] || value || '-'
  }

  return {
    viewMode,
    capacityLines,
    capacityOrders,
    operationSchedules,
    capacityLoading,
    capacityProcessFilter,
    capacityLineFilter,
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
    lineLabel,
    standardScopeLabel,
  }
}
