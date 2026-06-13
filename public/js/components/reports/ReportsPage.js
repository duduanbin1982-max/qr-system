// ReportsPage Component - 8-Tab Statistics & Reports (refactored)
import { ref, computed, onMounted } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=58'
import { showToast } from '../../store.js?v=58'

// === Shared utilities ===

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

function statusLabel(s) {
  const map = { pending: '\u5F85\u751F\u4EA7', producing: '\u751F\u4EA7\u4E2D', completed: '\u5DF2\u5B8C\u6210', paused: '\u5DF2\u6682\u505C', cancelled: '\u5DF2\u53D6\u6D88' }
  return map[s] || s
}

const TABS = [
  { k: 'dashboard', l: '\uD83D\uDCCA \u7EFC\u5408\u770B\u677F' },
  { k: 'trend', l: '\uD83D\uDCC8 \u751F\u4EA7\u8D8B\u52BF' },
  { k: 'worker', l: '\uD83D\uDC77 \u5DE5\u4EBA\u6548\u7387' },
  { k: 'quality', l: '\uD83D\uDD0D \u54C1\u8D28\u5206\u6790' },
  { k: 'order', l: '\uD83D\uDCCB \u8BA2\u5355\u5206\u6790' },
  { k: 'product', l: '\uD83C\uDFF7\uFE0F \u4EA7\u54C1\u7EDF\u8BA1' },
  { k: 'material', l: '\uD83D\uDCE6 \u7269\u6599\u6D88\u8017' },
  { k: 'shipment', l: '\uD83D\uDE9A \u53D1\u8D27\u7EDF\u8BA1' },
]

// Generic loader wrapper (R3.4 fixed)
function createLoader(ctx, fetchFn) {
  return async function() {
    ctx.loading.value = true
    try {
      await fetchFn()
      ctx.updateTime.value = new Date().toLocaleString('zh-CN')
    } catch (e) { showToast(e.message, 'error') }
    finally { ctx.loading.value = false }
  }
}

// Generic CSV exporter (R3.5 fixed)
function createExporter(dataRef, headers, rowMapper, filePrefix) {
  return function() {
    const arr = dataRef.value
    if (!arr || !arr.length) { showToast('\u6CA1\u6709\u6570\u636E\u53EF\u5BFC\u51FA', 'warning'); return }
    const data = [headers]
    arr.forEach((item, i) => data.push(rowMapper(item, i)))
    exportCSV(data, filePrefix + '_' + new Date().toISOString().slice(0, 10))
  }
}

function buildParams(start, end) {
  const p = {}
  if (start.value) p.start = start.value
  if (end.value) p.end = end.value
  return p
}

// === Component ===
export default {
  template: '#reports-page-template',
  setup() {
    const tab = ref('dashboard')
    const loading = ref(false)
    const updateTime = ref('')
    const ctx = { tab, loading, updateTime }

    const reportStart = ref('')
    const reportEnd = ref('')

    function initDates() {
      const now = new Date()
      const local = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
      reportEnd.value = local(now)
      reportStart.value = local(new Date(now - 30 * 86400000))
      updateTime.value = now.toLocaleString('zh-CN')
    }

    // ---- Dashboard ----
    const kpi = ref({})
    const weeklyData = ref([])
    const weeklyMax = computed(() => Math.max(...weeklyData.value.map(d => d.output || 0), 1))
    const loadDashboard = createLoader(ctx, async () => {
      const d = await api.dashboardKpi()
      kpi.value = d
      weeklyData.value = d.weekly_trend || []
    })

    // ---- Trend ----
    const trendDays = ref(30)
    const trendData = ref([])
    const trendSummary = ref({})
    const trendMaxVal = computed(() =>
      Math.max(...trendData.value.map(t => Math.max(t.output, t.scrap, t.rework)), 1)
    )
    const loadTrend = createLoader(ctx, async () => {
      const d = await api.productionTrend({ days: trendDays.value })
      trendData.value = d.trend || []
      trendSummary.value = d.summary || {}
    })
    const exportTrend = createExporter(trendData,
      ['\u65E5\u671F', '\u4EA7\u91CF', '\u62A5\u5E9F', '\u62A5\u5E9F\u7387%', '\u8FD4\u5DE5', '\u8FD4\u5DE5\u7387%', '\u62A5\u5DE5\u6B21\u6570'],
      d => [d.date, d.output, d.scrap, d.output > 0 ? (d.scrap / d.output * 100).toFixed(1) : 0, d.rework, d.output > 0 ? (d.rework / d.output * 100).toFixed(1) : 0, d.report_count],
      '\u751F\u4EA7\u8D8B\u52BF'
    )

    // ---- Worker ----
    const workerStats = ref([])
    const loadWorker = createLoader(ctx, async () => {
      const d = await api.workerEfficiency(buildParams(reportStart, reportEnd))
      workerStats.value = d.workers || []
    })
    const exportWorker = createExporter(workerStats,
      ['\u6392\u540D', '\u59D3\u540D', '\u5DE5\u53F7', '\u603B\u4EA7\u51FA', '\u65E5\u5747', '\u5DE5\u4F5C\u5929\u6570', '\u62A5\u5DE5\u6B21\u6570', '\u62A5\u5E9F', '\u62A5\u5E9F\u7387%', '\u8FD4\u5DE5', '\u8FD4\u5DE5\u7387%'],
      (w, i) => [i + 1, w.name, w.employee_no || '', w.output, w.daily_avg, w.work_days, w.report_count, w.scrap, w.scrap_rate, w.rework, w.rework_rate],
      '\u5DE5\u4EBA\u6548\u7387'
    )

    // ---- Quality ----
    const qualityProcess = ref([])
    const qualityWorker = ref([])
    const loadQuality = createLoader(ctx, async () => {
      const d = await api.qualityAnalysis(buildParams(reportStart, reportEnd))
      qualityProcess.value = d.by_process || []
      qualityWorker.value = d.by_worker || []
    })
    const exportQuality = createExporter(qualityProcess,
      ['\u5DE5\u5E8F', '\u5206\u7C7B', '\u4EA7\u51FA', '\u62A5\u5E9F', '\u62A5\u5E9F\u7387%', '\u8FD4\u5DE5', '\u8FD4\u5DE5\u7387%', '\u4E0D\u826F\u5408\u8BA1'],
      p => [p.name, p.category || '', p.output || 0, p.scrap || 0, p.defect_rate || 0, p.rework || 0, (p.scrap || 0) + (p.rework || 0)],
      '\u54C1\u8D28\u5206\u6790'
    )

    // ---- Order ----
    const orderStatus = ref([])
    const orderMonthly = ref([])
    const loadOrder = createLoader(ctx, async () => {
      const d = await api.orderAnalysis(buildParams(reportStart, reportEnd))
      orderStatus.value = d.status_distribution || []
      orderMonthly.value = d.monthly_trend || []
    })
    const exportOrder = createExporter(orderStatus,
      ['\u72B6\u6001', '\u8BA2\u5355\u6570', '\u603B\u91CF', '\u5DF2\u5B8C\u6210', '\u5B8C\u6210\u7387%', '\u5269\u4F59'],
      s => [statusLabel(s.status), s.count, s.qty || 0, s.done || 0, (s.qty || 0) > 0 ? ((s.done || 0) / s.qty * 100).toFixed(1) : 0, Math.max(0, (s.qty || 0) - (s.done || 0))],
      '\u8BA2\u5355\u5206\u6790'
    )

    // ---- Product ----
    const productList = ref([])
    const productSummary = ref({})
    const loadProduct = createLoader(ctx, async () => {
      const d = await api.productStats(buildParams(reportStart, reportEnd))
      productList.value = d.by_product || []
      productSummary.value = d.summary || {}
    })
    const exportProduct = createExporter(productList,
      ['\u4EA7\u54C1\u540D\u79F0', '\u4EA7\u54C1\u7F16\u7801', '\u578B\u53F7', '\u89C4\u683C', '\u5206\u7C7B', '\u4EA7\u91CF', '\u62A5\u5E9F', '\u8FD4\u5DE5', '\u6D89\u53CA\u8BA2\u5355\u6570'],
      p => [p.product_name, p.product_code || '', p.model || '', p.spec || '', p.category || '', p.output, p.scrap, p.rework, p.order_count],
      '\u4EA7\u54C1\u7EDF\u8BA1'
    )

    // ---- Material ----
    const materialList = ref([])
    const materialSummary = ref({})
    const loadMaterial = createLoader(ctx, async () => {
      const d = await api.materialUsage(buildParams(reportStart, reportEnd))
      materialList.value = d.by_material || []
      materialSummary.value = d.summary || {}
    })
    const exportMaterial = createExporter(materialList,
      ['\u7269\u6599\u540D\u79F0', '\u89C4\u683C', '\u6750\u8D28', '\u5355\u4F4D', '\u5E93\u5B58', '\u6700\u4F4E\u5E93\u5B58', '\u5DF2\u6D88\u8017', '\u6D89\u53CA\u8BA2\u5355\u6570'],
      m => [m.name, m.spec || '', m.material_type || '', m.unit || '', m.stock_qty, m.safe_stock, m.total_used, m.order_count],
      '\u7269\u6599\u6D88\u8017'
    )

    // ---- Shipment ----
    const shipmentByStatus = ref([])
    const shipmentByCustomer = ref([])
    const shipmentMonthly = ref([])
    const loadShipment = createLoader(ctx, async () => {
      const d = await api.shipmentStats(buildParams(reportStart, reportEnd))
      shipmentByStatus.value = d.by_status || []
      shipmentByCustomer.value = d.by_customer || []
      shipmentMonthly.value = d.monthly_trend || []
    })
    const exportShipment = createExporter(shipmentByStatus,
      ['\u72B6\u6001', '\u53D1\u8D27\u6570', '\u603B\u6570\u91CF'],
      s => [statusLabel(s.status), s.count, s.total_qty],
      '\u53D1\u8D27\u7EDF\u8BA1'
    )

    // ---- Tab switch ----
    const loadMap = { dashboard: loadDashboard, trend: loadTrend, worker: loadWorker, quality: loadQuality,
      order: loadOrder, product: loadProduct, material: loadMaterial, shipment: loadShipment }

    function switchTab(t) { tab.value = t; if (loadMap[t]) loadMap[t]() }

    onMounted(() => { initDates(); loadDashboard() })

    return {
      tab, switchTab, loading, updateTime, TABS,
      reportStart, reportEnd,
      kpi, weeklyData, weeklyMax,
      trendDays, trendData, trendSummary, trendMaxVal, exportTrend,
      workerStats, exportWorker,
      qualityProcess, qualityWorker, exportQuality,
      orderStatus, orderMonthly, exportOrder,
      productList, productSummary, exportProduct,
      materialList, materialSummary, exportMaterial,
      shipmentByStatus, shipmentByCustomer, shipmentMonthly, exportShipment,
      statusLabel,
    }
  }
}
