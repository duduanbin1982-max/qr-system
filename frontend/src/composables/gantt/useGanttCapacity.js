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


export function useGanttCapacity({ orders, riskLevel }) {
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
  const replanOrderId = ref('')
  const replanStartAt = ref('')
  const replanReason = ref('根据实际报工、返工和停机动态重排')
  const replanRunKey = ref('')
  const downtimeEvents = ref([])
  const downtimeLoading = ref(false)
  const downtimeForm = ref({
    process_line_id: '',
    start_at: '',
    end_at: '',
    reason: '',
  })

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
      if (!downtimeForm.value.process_line_id && capacityLines.value.length) {
        downtimeForm.value.process_line_id = capacityLines.value[0].id
      }
    } catch (error) {
      showToast(error.message || '加载工序排程失败', 'error')
      capacityLines.value = []
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
    const form = downtimeForm.value
    if (!form.process_line_id) {
      showToast('请选择停机产线', 'error')
      return
    }
    if (!form.start_at || !form.end_at) {
      showToast('请填写停机开始和结束时间', 'error')
      return
    }
    if (new Date(form.end_at) <= new Date(form.start_at)) {
      showToast('停机结束时间必须晚于开始时间', 'error')
      return
    }
    try {
      await api.domains.production.createScheduleDowntime({
        process_line_id: Number(form.process_line_id),
        start_at: form.start_at,
        end_at: form.end_at,
        reason: String(form.reason || '').trim(),
      })
      showToast('停机记录已保存')
      form.start_at = ''
      form.end_at = ''
      form.reason = ''
      await loadDowntime()
    } catch (error) {
      showToast(error.message || '保存停机记录失败', 'error')
    }
  }

  async function cancelDowntime(event) {
    try {
      await api.domains.production.cancelScheduleDowntime(event.id)
      showToast('停机记录已取消')
      await loadDowntime()
    } catch (error) {
      showToast(error.message || '取消停机记录失败', 'error')
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

  function startDynamicReplan(order) {
    replanOrderId.value = order?.id || ''
    const now = new Date()
    const pad = (value) => String(value).padStart(2, '0')
    replanStartAt.value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`
    replanRunKey.value = `dynamic-replan-${order?.id || 'order'}-${Date.now()}`
  }

  function prepareDynamicReplan(orderId) {
    const order = capacityOrders.value.find(item => String(item.id) === String(orderId))
      || orders.value.find(item => String(item.id) === String(orderId))
    if (order) startDynamicReplan(order)
  }

  async function dynamicReplanSchedule() {
    if (!replanOrderId.value) {
      showToast('请选择订单', 'error')
      return
    }
    try {
      await api.domains.production.dynamicReplanOrderSchedule(replanOrderId.value, {
        start_at: replanStartAt.value,
        schedule_run_key: replanRunKey.value,
        reason: replanReason.value,
      })
      showToast('已按实际生产事实生成动态重排版本')
      await loadCapacity()
    } catch (error) {
      showToast(error.message || '动态重排失败', 'error')
    }
  }

  function lineLabel(row) {
    return row.line_name || (row.process_line_id ? `产线 #${row.process_line_id}` : '未分配')
  }

  function standardScopeLabel(scope) {
    const value = String(scope || '').trim()
    return STANDARD_SCOPE_LABELS[value] || value || '-'
  }

  function operationRisk(row) {
    const order = orders.value.find(item => String(item.id) === String(row.order_id))
      || capacityOrders.value.find(item => String(item.id) === String(row.order_id))
    return order || { risk_level: 'none', risk_reason: '订单交期风险信息尚未加载' }
  }

  function operationRiskLevel(row) {
    const order = operationRisk(row)
    return riskLevel ? riskLevel(order) : (order.risk_level || 'none')
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
    replanOrderId,
    replanStartAt,
    replanReason,
    replanRunKey,
    startDynamicReplan,
    prepareDynamicReplan,
    dynamicReplanSchedule,
    downtimeEvents,
    downtimeLoading,
    downtimeForm,
    loadDowntime,
    createDowntime,
    cancelDowntime,
    lineLabel,
    standardScopeLabel,
    operationRisk,
    operationRiskLevel,
  }
}
