import { computed, ref } from 'vue'
import { api } from '@/lib/api.js'

export function useWorkTimeAudit(props, emit) {
  const records = ref([])

  const isLoading = ref(false)

  const auditMode = ref('pending')

  const auditFilters = ref({ review_status: 'pending', status: '', process_id: '', date_from: '', date_to: '' })

  const auditQuickOptions = [
    { key: 'pending', label: '待审核', icon: '🟡', hint: '优先处理未确认工时', className: 'warning' },
    { key: 'abnormal', label: '异常工时', icon: '🔴', hint: '待料/设备/补录异常', className: 'danger' },
    { key: 'low_efficiency', label: '效率偏低', icon: '📉', hint: '标准/有效低于 80%', className: 'primary' },
    { key: 'all', label: '全部记录', icon: '📋', hint: '查看完整审核范围', className: 'default' },
  ]

  const visibleRecords = computed(() => {
    if (auditMode.value === 'low_efficiency') return records.value.filter(isLowEfficiency)
    return records.value
  })

  const emptyText = computed(() => {
    if (auditMode.value === 'low_efficiency') return '暂无效率低于 80% 的工时记录'
    if (auditMode.value === 'abnormal') return '暂无异常工时'
    if (auditMode.value === 'pending') return '暂无待审核工时'
    return '暂无工时审核记录'
  })

  async function load() {
    isLoading.value = true
    try {
      const params = { ...auditFilters.value, keyword: props.keyword, limit: 200 }
      const result = await api.domains.workTime.listWorkTimeRecords(params)
      records.value = result.items || []
    } finally {
      isLoading.value = false
    }
  }

  function setAuditMode(mode) {
    auditMode.value = mode
    if (mode === 'pending') auditFilters.value = { ...auditFilters.value, review_status: 'pending', status: '' }
    if (mode === 'abnormal') auditFilters.value = { ...auditFilters.value, review_status: '', status: 'abnormal' }
    if (mode === 'low_efficiency') auditFilters.value = { ...auditFilters.value, review_status: '', status: '' }
    if (mode === 'all') auditFilters.value = { ...auditFilters.value, review_status: '', status: '' }
    load()
  }

  function markCustomAndLoad() {
    auditMode.value = 'custom'
    load()
  }

  function resetAuditFilters() {
    auditMode.value = 'pending'
    auditFilters.value = { review_status: 'pending', status: '', process_id: '', date_from: '', date_to: '' }
    load()
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

  function isLowEfficiency(row) {
    const value = efficiencyValue(row)
    return value !== null && value < 80
  }

  function efficiencyClass(row) {
    return isLowEfficiency(row) ? 'efficiency-danger' : 'efficiency-normal'
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
    auditMode,
    auditFilters,
    auditQuickOptions,
    visibleRecords,
    emptyText,
    load,
    setAuditMode,
    markCustomAndLoad,
    resetAuditFilters,
    efficiencyValue,
    efficiency,
    isLowEfficiency,
    efficiencyClass,
    recordStatusLabel,
    recordStatusClass,
    reviewStatusLabel,
    reviewStatusClass
  }
}
