import { ref, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
import { exportCSV } from '@/composables/reports/reportSupport.js'

function buildDailyDetailCsvRows(groups, workNumber) {
  const rows = [['员工姓名', '工号', '岗位', '报工时间', '订单号/序列号', '产品编码', '正常数量', '返修数量', '报废数量']]
  groups.forEach(group => {
    group.records.forEach(record => {
      const qty = record.quantity ?? 0
      // Match the existing group totals: an empty legacy type is normal work.
      const normal = record.type !== 'rework' && record.type !== 'scrap'
      rows.push([
        group.worker_name || '', group.employee_no || '', group.position_name || '',
        record.created_at || '', workNumber(record) || '', record.product_code || '',
        normal ? qty : 0, record.type === 'rework' ? qty : 0, record.type === 'scrap' ? qty : 0,
      ])
    })
  })
  return rows
}

export function useDailyStats(props) {
  const dailyRecords = ref([])
  const dailySummary = ref([])
  const dailyGroups = ref([])
  const summaryTotals = ref({})
  const workTimeSummary = ref({})
  const isTruncated = ref(false)
  const loading = ref(true)
  const employeeSearch = ref('')
  const typeFilter = ref('')
  const openGroups = ref({})
  const canExport = computed(() => can('stats:view'))

  function quantity(value) {
    const number = Number(value || 0)
    return Number.isFinite(number) ? number : 0
  }

  function rate(part, total) {
    const denominator = quantity(total)
    return denominator ? Math.round(quantity(part) / denominator * 10000) / 100 : 0
  }

  function groupKey(group) {
    return String(group.user_id || group.employee_no || group.worker_name || 'unknown')
  }

  function isGroupOpen(key) {
    return openGroups.value[key] !== false
  }

  function toggleGroup(key) {
    openGroups.value = { ...openGroups.value, [key]: !isGroupOpen(key) }
  }

  function summarizeGroup(group, records) {
    const orderSet = new Set()
    const productSet = new Set()
    const result = { ...group, records, record_count: records.length, total_quantity: 0, normal_quantity: 0, scrap_quantity: 0, rework_quantity: 0 }
    records.forEach(record => {
      const qty = quantity(record.quantity)
      result.total_quantity += qty
      if (record.type === 'scrap') result.scrap_quantity += qty
      else if (record.type === 'rework') result.rework_quantity += qty
      else result.normal_quantity += qty
      if (record.order_id) orderSet.add(record.order_id)
      const productKey = record.product_code || record.product_name || ''
      if (productKey) productSet.add(productKey)
    })
    ;['total_quantity', 'normal_quantity', 'scrap_quantity', 'rework_quantity'].forEach(key => {
      if (Number.isInteger(result[key])) result[key] = Number(result[key])
    })
    result.order_count = orderSet.size
    result.product_count = productSet.size
    result.scrap_rate = rate(result.scrap_quantity, result.total_quantity)
    result.rework_rate = rate(result.rework_quantity, result.total_quantity)
    return result
  }

  const filteredEmployeeGroups = computed(() => {
    const keyword = (employeeSearch.value || '').toLowerCase()
    return dailyGroups.value.map(group => {
      const target = [group.worker_name, group.employee_no, group.group_name, group.department_name, group.position_name].join(' ').toLowerCase()
      if (keyword && !target.includes(keyword)) return null
      const records = (group.records || []).filter(record => !typeFilter.value || record.type === typeFilter.value)
      if (!records.length) return null
      return summarizeGroup(group, records)
    }).filter(Boolean)
  })

  const detailRecordCount = computed(() => filteredEmployeeGroups.value.reduce((sum, group) => sum + group.records.length, 0))

  function isValidDate(str) {
    if (!str) return true
    if (!/^\d{4}-\d{2}-\d{2}$/.test(str)) return false
    const [y, m, d] = str.split('-').map(Number)
    const dt = new Date(y, m - 1, d)
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d
  }

  function todayLocal() {
    const d = new Date()
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
  }

  function fallbackGroups(records) {
    const map = new Map()
    records.forEach(record => {
      const key = record.user_id || record.employee_no || record.worker_name || 'unknown'
      if (!map.has(key)) map.set(key, { user_id: record.user_id, worker_name: record.worker_name, employee_no: record.employee_no, group_name: record.group_name, department_name: record.department_name, position_name: record.position_name, records: [] })
      map.get(key).records.push(record)
    })
    return Array.from(map.values()).map(group => summarizeGroup(group, group.records))
  }

  async function loadDaily() {
    const d = props.date || todayLocal()
    if (!isValidDate(d)) {
      showToast('日期格式无效', 'warning')
      loading.value = false
      return
    }
    loading.value = true
    try {
      const params = { date: d, per_page: 5000 }
      if (props.productCode) params.product_code = props.productCode
      const res = await api.domains.stats.dailyStats(params)
      dailyRecords.value = res.records || []
      dailySummary.value = res.summary || []
      dailyGroups.value = (res.employee_groups && res.employee_groups.length) ? res.employee_groups : fallbackGroups(dailyRecords.value)
      summaryTotals.value = res.summary_totals || {}
      workTimeSummary.value = res.work_time_summary || {}
      isTruncated.value = !!res.is_truncated
      const nextOpen = {}
      dailyGroups.value.forEach(group => { nextOpen[groupKey(group)] = openGroups.value[groupKey(group)] !== false })
      openGroups.value = nextOpen
    } catch (e) { showToast(e.message, 'error') } finally { loading.value = false }
  }

  function displayWorkNo(record) {
    if (record.qr_mode === 'serial' && record.serial_no) return record.serial_no
    return record.display_order_no || record.order_no
  }

  function timeOnly(value) {
    return value ? String(value).slice(11, 19) || value : '-'
  }

  function productMeta(record) {
    return [record.product_model, record.product_spec, record.product_category].filter(Boolean).join(' / ') || '-'
  }

  function typeLabel(type) {
    return type === 'scrap' ? '报废' : type === 'rework' ? '返修' : '正常'
  }

  function typeClass(type) {
    return type === 'scrap' ? 'badge-danger' : type === 'rework' ? 'badge-warning' : 'badge-success'
  }

  function qualityText(record) {
    const parts = []
    if (record.quality_result) parts.push(record.quality_result)
    if (record.quality_score) parts.push(String(record.quality_score) + '分')
    return parts.join(' / ')
  }

  function exportSummaryCsv() {
    if (!dailySummary.value.length) { showToast('没有数据可导出', 'warning'); return }
    const data = [['工序','报工次数','产出','报废','返修']]
    dailySummary.value.forEach(s => data.push([s.name, s.record_count, s.total_output, s.total_scrap, s.total_rework]))
    exportCSV(data, '日报表_工序汇总_' + (props.date || ''))
  }

  function exportDetailCsv() {
    if (isTruncated.value) { showToast('数据已截断，请缩小筛选范围后再导出明细', 'warning'); return }
    if (!detailRecordCount.value) { showToast('没有数据可导出', 'warning'); return }
    const data = buildDailyDetailCsvRows(filteredEmployeeGroups.value, displayWorkNo)
    exportCSV(data, '日报表_员工明细_' + (props.date || ''))
  }

  watch(() => [props.date, props.productCode], loadDaily, { immediate: true })
  return {
    dailyRecords, dailySummary, dailyGroups, summaryTotals, workTimeSummary, isTruncated, loading,
    employeeSearch, typeFilter, filteredEmployeeGroups, detailRecordCount, canExport,
    loadDaily, displayWorkNo, exportSummaryCsv, exportDetailCsv, groupKey, isGroupOpen,
    toggleGroup, timeOnly, productMeta, typeLabel, typeClass, qualityText,
  }
}
