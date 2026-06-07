// StatsPage Component — 统计报表（4标签：日报/员工计件/报废/订单进度）
import { ref, computed, onMounted } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { can } from '../../auth.js?v=56'

// CSV export utility
function exportCSV(data, filename) {
  const BOM = '\uFEFF'
  const csv = BOM + data.map(row => row.map(c => {
    const s = String(c == null ? '' : c)
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename + '.csv'
  a.click(); URL.revokeObjectURL(url)
}

export default {
  template: '#stats-page-template',
  setup() {
    const tab = ref('daily')
    const loading = ref(false)

    // RBAC
    const canExport = computed(() => can('stats:export'))

    // ===== Daily =====
    const dailyDate = ref(new Date().toISOString().slice(0, 10))
    const dailyRecords = ref([])
    const dailySummary = ref([])

    async function loadDaily() {
      loading.value = true
      try {
        const d = await api.dailyStats({ date: dailyDate.value })
        dailyRecords.value = d.records || []
        dailySummary.value = d.summary || []
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }
    function exportDaily() {
      if (!dailySummary.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['工序', '报工次数', '产出', '报废', '返修']]
      dailySummary.value.forEach(s => data.push([s.name, s.record_count, s.total_output, s.total_scrap, s.total_rework]))
      exportCSV(data, '生产日报表_' + dailyDate.value)
    }

    // ===== Worker =====
    const wStart = ref('')
    const wEnd = ref('')
    const workers = ref([])

    async function loadWorker() {
      loading.value = true
      try {
        const params = {}
        if (wStart.value) params.start = wStart.value
        if (wEnd.value) params.end = wEnd.value
        const d = await api.workerStats(params)
        workers.value = d.workers || []
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }


    // ===== Scrap =====
    const sStart = ref('')
    const sEnd = ref('')
    const scrapRecords = ref([])

    async function loadScrap() {
      loading.value = true
      try {
        const params = {}
        if (sStart.value) params.start = sStart.value
        if (sEnd.value) params.end = sEnd.value
        const d = await api.scrapStats(params)
        scrapRecords.value = d.records || []
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    // ===== Progress =====
    const progressOrders = ref([])

    const progressStats = computed(() => {
      const data = progressOrders.value
      return {
        count: data.length,
        qty: data.reduce((s, o) => s + (o.quantity || 0), 0),
        completed: data.reduce((s, o) => s + (o.completed || 0), 0),
        near80: data.filter(o => {
          const pct = o.quantity > 0 ? Math.round((o.completed || 0) / o.quantity * 100) : 0
          return pct >= 80
        }).length,
      }
    })

    async function loadProgress() {
      loading.value = true
      try {
        const d = await api.orderProgress()
        progressOrders.value = d.orders || []
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    function progressPct(o) {
      return o.quantity > 0 ? Math.min(Math.round((o.completed || 0) / o.quantity * 100), 100) : 0
    }
    function progressClass(o) {
      const pct = progressPct(o)
      if (pct >= 100) return 'full'
      if (pct >= 50) return 'mid'
      return 'low'
    }
    function exportProgress() {
      if (!progressOrders.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['#', '订单号', '客户', '产品', '数量', '已完成', '进度', '计划完成', '状态']]
      progressOrders.value.forEach((o, i) => {
        data.push([i + 1, o.order_no, o.customer, o.product_name, o.quantity, o.completed, progressPct(o) + '%', o.plan_end || '', o.status])
      })
      exportCSV(data, '订单进度表')
    }

    function switchTab(t) {
      tab.value = t
      if (t === 'daily') loadDaily()
      else if (t === 'worker') loadWorker()

      else if (t === 'scrap') loadScrap()
      else if (t === 'progress') loadProgress()
    }

    onMounted(() => loadDaily())

    return {
      tab, switchTab, loading,
      dailyDate, dailyRecords, dailySummary, loadDaily, exportDaily,
      wStart, wEnd, workers, loadWorker,

      sStart, sEnd, scrapRecords, loadScrap,
      progressOrders, progressStats, loadProgress, progressPct, progressClass, exportProgress,
      canExport,
    }
  }
}
