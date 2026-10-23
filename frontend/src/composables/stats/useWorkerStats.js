import { ref, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV } from '@/composables/reports/reportSupport.js'

export function useWorkerStats(props) {
  const workers = ref([])
  const expanded = ref(null)
  const detailRows = ref([])
  const loadingDetail = ref(null)

  async function loadWorker() {
    try {
      const params = {}
      if (props.start) params.start = props.start
      if (props.end) params.end = props.end
      if (props.productCode) params.product_code = props.productCode
      const d = await api.domains.stats.workerStats(params)
      workers.value = d.workers || []
    } catch (e) { showToast(e.message, 'error') }
  }

  async function toggleRow(uid) {
    if (expanded.value === uid) {
      expanded.value = null
      detailRows.value = []
      return
    }
    expanded.value = uid
    loadingDetail.value = uid
    detailRows.value = []
    try {
      const params = { user_id: uid }
      if (props.start) params.start = props.start
      if (props.end) params.end = props.end
      const d = await api.domains.stats.workerDetail(params)
      detailRows.value = d.rows || []
    } catch (e) { showToast(e.message, 'error') }
    loadingDetail.value = null
  }

  function exportCsv() {
    if (!workers.value.length) { showToast('没有数据可导出', 'warning'); return }
    const data = [['#','姓名','工号','出勤天数','报工次数','产出','报废']]
    workers.value.forEach((w,i) => data.push([i+1, w.name, w.employee_no||'', w.work_days||0, w.record_count, w.total_output, w.total_scrap]))
    const dateTag = props.start ? props.start + '_' + (props.end || '') : new Date().toISOString().slice(0, 10)
    exportCSV(data, '员工计件_' + dateTag)
  }

  onMounted(loadWorker)
  return { workers, expanded, detailRows, loadingDetail, toggleRow, exportCsv }
}
