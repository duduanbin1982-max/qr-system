import { computed, ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useWorkTimeRecords(props, emit) {
  const records = ref([])

  const isLoading = ref(false)

  const isSaving = ref(false)

  const isSearchingOrders = ref(false)

  const recordFilters = ref({ review_status: '', status: '', process_id: '', standard_missing: '', date_from: '', date_to: '' })

  const recordForm = ref({})

  const orderKeyword = ref('')

  const orderOptions = ref([])

  const standardMatch = ref(null)

  const standardChecked = ref(false)

  const standardChecking = ref(false)

  const showRecordModal = ref(false)

  const hasRecordFilters = computed(() => Object.values(recordFilters.value).some(Boolean))

  const selectedOrder = computed(() => orderOptions.value.find(order => String(order.id) === String(recordForm.value.order_id)) || null)

  const availableProcesses = computed(() => {
    const orderProcesses = selectedOrder.value?.processes || []
    return orderProcesses.length ? orderProcesses : props.processes
  })

  const standardStatus = computed(() => {
    if (!recordForm.value.order_id) return { text: '未关联订单', class: 'standard-muted' }
    if (!recordForm.value.process_id) return { text: '选择工序后自动匹配', class: 'standard-muted' }
    if (standardChecking.value) return { text: '正在匹配...', class: 'standard-muted' }
    if (!standardChecked.value) return { text: '待匹配', class: 'standard-muted' }
    if (standardMatch.value) {
      const unit = formatMinute(standardMatch.value.standard_minutes_per_unit)
      const setup = formatMinute(standardMatch.value.setup_minutes)
      return { text: `已匹配，单件 ${unit} 分，准备 ${setup} 分`, class: 'standard-ok' }
    }
    return { text: '缺少该路线工序标准工时，保存后会标记缺标准', class: 'standard-warning' }
  })

  function nowLocalInput() {
    const d = new Date()
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
    return d.toISOString().slice(0, 16)
  }

  function processValue(process) {
    return process.process_id || process.id
  }

  function processName(process) {
    return process.process_name || process.name || '-'
  }

  function formatMinute(value) {
    const number = Number(value || 0)
    return Number.isInteger(number) ? String(number) : String(Math.round(number * 10) / 10)
  }

  function resetStandardCheck() {
    standardMatch.value = null
    standardChecked.value = false
    standardChecking.value = false
  }

  async function checkStandardMatch() {
    resetStandardCheck()
    if (!recordForm.value.route_id || !recordForm.value.process_id) return
    standardChecking.value = true
    try {
      const result = await api.domains.workTime.listWorkTimeStandards({
        route_id: recordForm.value.route_id,
        process_id: recordForm.value.process_id,
        status: 'active',
        limit: 1,
      })
      standardMatch.value = (result.items || [])[0] || null
      standardChecked.value = true
    } catch (error) {
      standardChecked.value = true
      standardMatch.value = null
    } finally {
      standardChecking.value = false
    }
  }

  async function load() {
    isLoading.value = true
    try {
      const params = { ...recordFilters.value, keyword: props.keyword, limit: 200 }
      const result = await api.domains.workTime.listWorkTimeRecords(params)
      records.value = result.items || []
    } finally {
      isLoading.value = false
    }
  }

  function clearRecordFilters() {
    recordFilters.value = { review_status: '', status: '', process_id: '', standard_missing: '', date_from: '', date_to: '' }
    load()
  }

  async function searchOrders() {
    isSearchingOrders.value = true
    try {
      const result = await api.domains.orders.listOrders({ keyword: orderKeyword.value, limit: 50, archive: 'all' })
      orderOptions.value = result.orders || result.items || []
      if (!orderOptions.value.length) showToast('未找到匹配订单', 'warning')
    } catch (error) {
      showToast(error.message || '订单搜索失败', 'error')
    } finally {
      isSearchingOrders.value = false
    }
  }

  async function selectOrderById() {
    const order = selectedOrder.value
    if (!order) {
      recordForm.value = { ...recordForm.value, order_id: '', route_id: '', route_name: '', product_code: '', product_name: '' }
      resetStandardCheck()
      return
    }
    recordForm.value = {
      ...recordForm.value,
      order_id: order.id,
      order_no: order.order_no || '',
      product_code: order.product_code || '',
      product_name: order.product_name || '',
      route_id: order.route_id || '',
      route_name: order.route_name || '',
    }
    const allowedIds = (order.processes || []).map(item => String(processValue(item)))
    if (allowedIds.length && !allowedIds.includes(String(recordForm.value.process_id))) {
      recordForm.value.process_id = ''
    }
    await checkStandardMatch()
  }

  async function handleProcessChange() {
    await checkStandardMatch()
  }

  async function openRecord() {
    const start = nowLocalInput()
    recordForm.value = {
      order_id: '',
      order_no: '',
      serial_no: '',
      route_id: '',
      route_name: '',
      product_code: '',
      product_name: '',
      process_id: '',
      user_id: '',
      quantity: 1,
      start_time: start,
      end_time: start,
      pause_minutes: 0,
      effective_minutes: '',
      status: 'completed',
      abnormal_reason: '',
    }
    orderKeyword.value = ''
    orderOptions.value = []
    resetStandardCheck()
    showRecordModal.value = true
    await searchOrders()
  }

  async function saveRecord() {
    try {
      isSaving.value = true
      await api.domains.workTime.createWorkTimeRecord({ ...recordForm.value })
      showToast('工时流水已保存')
      showRecordModal.value = false
      await load()
      emit('changed')
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    } finally {
      isSaving.value = false
    }
  }

  function efficiencyValue(row) {
    const standard = Number(row.standard_minutes || 0)
    const effective = Number(row.effective_minutes || 0)
    if (!standard || !effective) return null
    return Math.round(standard * 1000 / effective) / 10
  }

  function efficiency(row) {
    const value = efficiencyValue(row)
    return value === null ? '-' : value + '%'
  }

  function efficiencyClass(row) {
    const value = efficiencyValue(row)
    if (value === null) return 'efficiency-muted'
    return value < 80 ? 'efficiency-danger' : 'efficiency-normal'
  }

  function standardCellText(row) {
    if (Number(row.standard_missing || 0) === 1) return '缺标准工时'
    return `${row.standard_minutes || 0} 分`
  }

  function standardCellClass(row) {
    return Number(row.standard_missing || 0) === 1 ? 'standard-warning' : 'standard-ok'
  }

  function recordStatusLabel(status) {
    return { running: '进行中', completed: '已完成', abnormal: '异常' }[status] || status || '-'
  }

  function recordStatusClass(status) {
    return status === 'completed' ? 'badge-success' : status === 'abnormal' ? 'badge-danger' : 'badge-warning'
  }

  function reviewStatusLabel(status) {
    return { pending: '待审核', approved: '已通过', rejected: '已驳回' }[status] || status || '-'
  }

  function reviewStatusClass(status) {
    return status === 'approved' ? 'badge-success' : status === 'rejected' ? 'badge-danger' : 'badge-warning'
  }

  return {
    records,
    isLoading,
    isSaving,
    isSearchingOrders,
    recordFilters,
    recordForm,
    orderKeyword,
    orderOptions,
    standardMatch,
    standardChecked,
    standardChecking,
    showRecordModal,
    hasRecordFilters,
    selectedOrder,
    availableProcesses,
    standardStatus,
    nowLocalInput,
    processValue,
    processName,
    formatMinute,
    resetStandardCheck,
    checkStandardMatch,
    load,
    clearRecordFilters,
    searchOrders,
    selectOrderById,
    handleProcessChange,
    openRecord,
    saveRecord,
    efficiencyValue,
    efficiency,
    efficiencyClass,
    standardCellText,
    standardCellClass,
    recordStatusLabel,
    recordStatusClass,
    reviewStatusLabel,
    reviewStatusClass
  }
}
