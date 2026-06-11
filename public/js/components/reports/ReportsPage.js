// ReportsPage Component — 数据分析报表（生产趋势/工人效率/品质分析/订单分析）
import { ref, computed, onMounted } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'

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

function statusLabel(s) {
  const map = { pending: '待生产', producing: '生产中', completed: '已完成', paused: '已暂停', cancelled: '已取消' }
  return map[s] || s
}

export default {
  template: '#reports-page-template',
  setup() {
    const tab = ref('trend')
    const loading = ref(false)
    const updateTime = ref('')

    // ===== 生产趋势 =====
    const trendDays = ref(30)
    const trendData = ref([])
    const trendSummary = ref({})

    const trendMaxVal = computed(() =>
      Math.max(...trendData.value.map(t => Math.max(t.output, t.scrap, t.rework)), 1)
    )

    async function loadTrend() {
      loading.value = true
      try {
        const d = await api.productionTrend({ days: trendDays.value })
        trendData.value = d.trend || []
        trendSummary.value = d.summary || {}
        updateTime.value = new Date().toLocaleString('zh-CN')
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    function exportTrend() {
      if (!trendData.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['日期', '产量', '报废', '报废率%', '返工', '返工率%', '报工次数']]
      trendData.value.forEach(d => {
        const sr = d.output > 0 ? (d.scrap / d.output * 100).toFixed(1) : 0
        const rr = d.output > 0 ? (d.rework / d.output * 100).toFixed(1) : 0
        data.push([d.date, d.output, d.scrap, sr, d.rework, rr, d.report_count])
      })
      exportCSV(data, '生产趋势_' + new Date().toISOString().slice(0, 10))
    }

    // ===== 工人效率 =====
    const reportStart = ref('')
    const reportEnd = ref('')
    const workerStats = ref([])

    async function loadWorker() {
      loading.value = true
      try {
        const params = {}
        if (reportStart.value) params.start = reportStart.value
        if (reportEnd.value) params.end = reportEnd.value
        const d = await api.workerEfficiency(params)
        workerStats.value = d.workers || []
        updateTime.value = new Date().toLocaleString('zh-CN')
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    function exportWorker() {
      if (!workerStats.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['排名', '姓名', '工号', '总产出', '日均', '工作天数', '报工次数', '报废', '报废率%', '返工', '返工率%']]
      workerStats.value.forEach((w, i) => {
        data.push([i + 1, w.name, w.employee_no || '', w.output, w.daily_avg, w.work_days, w.report_count, w.scrap, w.scrap_rate, w.rework, w.rework_rate])
      })
      exportCSV(data, '工人效率_' + new Date().toISOString().slice(0, 10))
    }

    // ===== 品质分析 =====
    const qualityProcess = ref([])
    const qualityWorker = ref([])

    async function loadQuality() {
      loading.value = true
      try {
        const params = {}
        if (reportStart.value) params.start = reportStart.value
        if (reportEnd.value) params.end = reportEnd.value
        const d = await api.qualityAnalysis(params)
        qualityProcess.value = d.by_process || []
        qualityWorker.value = d.by_worker || []
        updateTime.value = new Date().toLocaleString('zh-CN')
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    function exportQuality() {
      if (!qualityProcess.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['工序', '分类', '产出', '报废', '报废率%', '返工', '返工率%', '不良合计']]
      qualityProcess.value.forEach(p => {
        const out = p.output || 0
        const scrapRate = out > 0 ? ((p.scrap || 0) / out * 100).toFixed(1) : "0.0"
        const reworkRate = out > 0 ? ((p.rework || 0) / out * 100).toFixed(1) : "0.0"
        data.push([p.name, p.category || "", out, p.scrap || 0, scrapRate, p.rework || 0, reworkRate, (p.scrap || 0) + (p.rework || 0)])
      })
      exportCSV(data, '品质分析_' + new Date().toISOString().slice(0, 10))
    }

    // ===== 订单分析 =====
    const orderStatus = ref([])
    const orderMonthly = ref([])

    async function loadOrder() {
      loading.value = true
      try {
        const params = {}
        if (reportStart.value) params.start = reportStart.value
        if (reportEnd.value) params.end = reportEnd.value
        const d = await api.orderAnalysis(params)
        orderStatus.value = d.status_distribution || []
        orderMonthly.value = d.monthly_trend || []
        updateTime.value = new Date().toLocaleString('zh-CN')
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    function exportOrder() {
      if (!orderStatus.value.length) { showToast('没有数据可导出', 'warning'); return }
      const data = [['状态', '订单数', '总量', '已完成', '完成率%', '剩余']]
      orderStatus.value.forEach(s => {
        const rate = (s.qty || 0) > 0 ? ((s.done || 0) / s.qty * 100).toFixed(1) : 0
        const remain = Math.max(0, (s.qty || 0) - (s.done || 0))
        data.push([statusLabel(s.status), s.count, s.qty || 0, s.done || 0, rate, remain])
      })
      exportCSV(data, '订单分析_' + new Date().toISOString().slice(0, 10))
    }

    // ===== Tab 切换 & 数据加载 =====
    function switchTab(t) {
      tab.value = t
      loadData()
    }

    function loadData() {
      if (tab.value === 'trend') loadTrend()
      else if (tab.value === 'worker') loadWorker()
      else if (tab.value === 'quality') loadQuality()
      else if (tab.value === 'order') loadOrder()
    }

    function initDates() {
      const now = new Date()
      const local = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
      reportEnd.value = local(now)
      reportStart.value = local(new Date(now - 30 * 86400000))
      updateTime.value = now.toLocaleString('zh-CN')
    }

    onMounted(() => {
      initDates()
      loadData()
    })

    return {
      tab, switchTab, loading, updateTime,
      // Trend
      trendDays, trendData, trendSummary, trendMaxVal, loadTrend, exportTrend,
      // Worker
      reportStart, reportEnd, workerStats, loadWorker, exportWorker,
      // Quality
      qualityProcess, qualityWorker, loadQuality, exportQuality,
      // Order
      orderStatus, orderMonthly, loadOrder, exportOrder,
      // Helpers
      statusLabel,
    }
  }
}
