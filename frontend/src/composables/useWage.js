import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

const PROCESS_COLORS = ['#f59e0b','#3b82f6','#10b981','#8b5cf6','#ef4444','#06b6d4','#f97316','#84cc16','#ec4899','#6366f1']

export function buildPieceworkCsvRows(wages, fmtDate, fmtMoney) {
  const rows = [["姓名","岗位","工号","日期","订单号","产品","产品编码","工序","数量","单价","工资"]]
  let totalQuantity = 0
  let totalWage = 0
  for (const w of (wages || [])) {
    for (const d of (w.details || [])) {
      rows.push([w.employee_name, w.position_name || "", w.employee_no, fmtDate(d.date), d.order_no, d.product_name, d.product_code || "", d.process_name, d.quantity, fmtMoney(d.unit_price), fmtMoney(d.wage)])
    }
    rows.push([w.employee_name, w.position_name || "", w.employee_no, "", "", "", "", "小计", w.total_quantity, "", fmtMoney(w.total_wage)])
    totalQuantity += Number(w.total_quantity || 0)
    totalWage += Number(w.total_wage || 0)
  }
  rows.push(["", "", "", "", "", "", "", "合计", totalQuantity, "", fmtMoney(totalWage)])
  return rows
}

let _instance = null

export function useWage() {
  if (_instance) return _instance
const preferredTab = localStorage.getItem('wageActiveTab')
const activeTab = ref(preferredTab || (can('wages:view_all') || can('wages:prepare') || can('wages:approve') ? "ledger" : "my"))
    const tabs = computed(() => [
      { id:"ledger", label:"批次台账", show:can('wages:view_all') || can('wages:prepare') || can('wages:approve') },
      { id:"exceptions", label:"异常处理", show:can('wages:view_all') || can('wages:prepare') || can('wages:approve') },
      { id:"adjustment", label:"调整项", show:can('wages:view_all') || can('wages:prepare') || can('wages:approve') },
      { id:"priceversions", label:"工价版本", show:can('wages:prepare') || can('wages:approve') },
      { id:"my", label:"我的工资", show:can('wages:view_self') || can('wages:view_all') || can('wages:prepare') || can('wages:approve') },
      { id:"piece", label:"实时预估", show:can('wages:view') },
      { id:"monthly", label:"月度汇总", icon:"📊" },
      { id:"process", label:"工序分析", icon:"🔧" },
      { id:"compare", label:"工资对比", icon:"📈" },
      { id:"trend", label:"历史趋势", icon:"📈" },
      { id:"position", label:"岗位汇总", icon:"👥" },
      { id:"predict", label:"工资预测", icon:"🔮" }
    ].filter(tab => tab.show !== false))

    // --- piece wage state ---
    const wages = ref([])
    const loading = ref(false)
    const dateFrom = ref("")
    const dateTo = ref("")
    const expandedId = ref(null)
    const includeRework = ref(false)
    const hideZero = ref(false)
    const page = ref(1)
    const limit = ref(50)
    const total = ref(0)
    let _refreshTimer = null

    const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))

    function fmtMoney(v) { return Number(v || 0).toFixed(2) }
    function fmtDate(s) { if (!s) return ""; const m = s.match(/^\d{4}-\d{2}-\d{2}/); return m ? m[0] : s }

    function buildDailyGroups(details) {
      if (!details || !details.length) return []
      const map = {}
      for (const d of details) {
        const day = fmtDate(d.date)
        if (!map[day]) map[day] = { date: day, qty: 0, wage: 0, details: [] }
        map[day].qty += d.quantity || 0
        map[day].wage += d.wage || 0
        map[day].details.push(d)
      }
      return Object.values(map).sort((a,b) => a.date.localeCompare(b.date))
    }

    async function load(pg) {
      if (pg !== undefined) page.value = pg
      loading.value = true
      const params = {}
      if (dateFrom.value) params.date_from = dateFrom.value
      if (dateTo.value) params.date_to = dateTo.value
      if (includeRework.value) params.include_rework = "1"
      if (hideZero.value) params.hide_zero = "1"
      params.page = page.value
      params.limit = limit.value
      try {
        const r = await api.domains.wages.listWages(params)
        const raw = r.wages || []
        wages.value = raw.map(w => ({ ...w }))
        total.value = r.total || 0
      } catch (e) { showToast("加载失败", "error") }
      finally { loading.value = false }
    }

    function toggle(id) { expandedId.value = expandedId.value === id ? null : id }

    const filteredWages = computed(() => {
      if (!hideZero.value) return wages.value
      return wages.value.filter(w => w.total_quantity > 0)
    })

    function grandTotal() { return filteredWages.value.reduce((s,w) => s + (w.total_wage||0), 0) }
    function grandQty() { return filteredWages.value.reduce((s,w) => s + (w.total_quantity||0), 0) }

    const currentMonth = computed(() => {
      if (dateFrom.value) return dateFrom.value.slice(0,7)
      const d = new Date(); return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")
    })

    function exportCSV() {
      const rows = buildPieceworkCsvRows(filteredWages.value, fmtDate, fmtMoney)
      const csv = "\uFEFF"+rows.map(r=>r.map(c=>{const s=String(c==null?"":c);return /[",\n]/.test(s)?'"'+s.replace(/"/g,"\"\"")+'"':s}).join(",")).join("\n")
      const blob=new Blob([csv],{type:"text/csv;charset=utf-8"})
      const url=URL.createObjectURL(blob)
      const a=document.createElement("a");a.href=url;a.download="工资明细_"+(dateFrom.value||"全部")+"_"+(dateTo.value||"全部")+".csv"
      a.click();URL.revokeObjectURL(url)
    }

    function prevPage(){if(page.value>1)load(page.value-1)}
    function nextPage(){if(page.value<totalPages.value)load(page.value+1)}

    function printPayslip(w) {
      const now = new Date()
      const month = dateFrom.value ? dateFrom.value.slice(0,7) : (now.getFullYear()+"-"+String(now.getMonth()+1).padStart(2,"0"))
      const html = "<!DOCTYPE html><html><head><meta charset=utf-8><title>工资条</title><style>body{font-family:Microsoft YaHei,sans-serif;max-width:400px;margin:0 auto;padding:20px}h2{text-align:center;margin:0 0 4px}h4{text-align:center;color:#666;margin:0 0 16px;font-weight:400}table{width:100%;border-collapse:collapse;margin:12px 0}td,th{border:1px solid #ddd;padding:6px 10px;font-size:14px}th{background:#f5f5f5;text-align:right;width:40%}td{text-align:left}.total{font-size:18px;font-weight:700;color:#e67e22}.footer{margin-top:20px;display:flex;justify-content:space-between;font-size:13px}@media print{body{padding:0}}</style></head><body><h2>工资条</h2><h4>"+month+" · 扫码报工生产管理系统</h4><table><tr><th>姓名</th><td>"+w.employee_name+"</td></tr><tr><th>工号</th><td>"+(w.employee_no||"-")+"</td></tr><tr><th>岗位</th><td>"+(w.position_name||"-")+"</td></tr><tr><th>总件数</th><td>"+w.total_quantity+"</td></tr><tr><th>计件工资</th><td class=total>¥"+fmtMoney(w.total_wage)+"</td></tr><tr><th>返工工资</th><td>¥"+fmtMoney(w.rework_wage||0)+"</td></tr><tr><th>合计</th><td class=total>¥"+fmtMoney((w.total_wage||0)+(w.rework_wage||0))+"</td></tr></table><div class=footer><span>员工签收：___________</span><span>日期：___________</span></div><script>window.onload=function(){window.print();setTimeout(function(){window.close()},500)}<\/script></body></html>"
      const win = window.open("","_blank","width=500,height=600")
      if (win) { win.document.write(html); win.document.close() }
      else { showToast("请允许弹出窗口以打印工资条","error") }
    }

    // --- monthly state ---
    const monthlyData = ref({ summary: [], grand_total_quantity: 0, grand_total_wage: 0 })
    const monthlyLoading = ref(true)
    const monthlyMonth = ref(new Date().getFullYear()+"-"+String(new Date().getMonth()+1).padStart(2,"0"))
    const monthlyPage = ref(1)
    const monthlyLimit = ref(50)
    const monthlyTotal = ref(0)
    const monthlyTotalPages = computed(() => Math.max(1, Math.ceil(monthlyTotal.value / monthlyLimit.value)))

    function monthlyPercent(wage) {
      if (!monthlyData.value.grand_total_wage) return 0
      return ((wage/monthlyData.value.grand_total_wage)*100).toFixed(1)
    }
    async function loadMonthly() {
      monthlyLoading.value = true
      try {
        const r = await api.domains.wages.getMonthlySummary({ year_month: monthlyMonth.value, page: monthlyPage.value, limit: monthlyLimit.value })
        monthlyData.value = r; monthlyTotal.value = r.total || 0
      } catch(e) { showToast("加载月度汇总失败","error") }
      finally { monthlyLoading.value = false }
    }
    function monthlyPrevPage(){if(monthlyPage.value>1){monthlyPage.value--;loadMonthly()}}
    function monthlyNextPage(){if(monthlyPage.value<monthlyTotalPages.value){monthlyPage.value++;loadMonthly()}}

    function exportMonthlyCSV() {
      const rows = [["排名","姓名","工号","总件数","总工资","占比"]]
      for (let i=0;i<monthlyData.value.summary.length;i++) {
        const s = monthlyData.value.summary[i]
        rows.push([i+1, s.employee_name, s.employee_no||"-", s.total_quantity, fmtMoney(s.total_wage), monthlyPercent(s.total_wage)+"%"])
      }
      rows.push(["","","合计",monthlyData.value.grand_total_quantity,"",fmtMoney(monthlyData.value.grand_total_wage),""])
      const csv = "\uFEFF"+rows.map(r=>r.map(c=>{const s=String(c==null?"":c);return /[",\n]/.test(s)?'"'+s.replace(/"/g,"\"\"")+'"':s}).join(",")).join("\n")
      const blob=new Blob([csv],{type:"text/csv;charset=utf-8"})
      const url=URL.createObjectURL(blob)
      const a=document.createElement("a");a.href=url;a.download="月度汇总_"+monthlyMonth.value+".csv"
      a.click();URL.revokeObjectURL(url)
    }

    // --- process state ---
    const processData = ref({ summary: [], grand_total_wage: 0 })
    const processLoading = ref(true)
    const processMonth = ref(new Date().getFullYear()+"-"+String(new Date().getMonth()+1).padStart(2,"0"))

    function processColor(i) { return PROCESS_COLORS[i % PROCESS_COLORS.length] }
    function processPercent(wage) {
      if (!processData.value.grand_total_wage) return 0
      return ((wage/processData.value.grand_total_wage)*100).toFixed(1)
    }
    function barHeight(qty) {
      const max = Math.max(...processData.value.summary.map(p=>p.total_quantity), 1)
      return Math.max(4, (qty/max)*100)
    }
    async function loadProcess() {
      processLoading.value = true
      try {
        const r = await api.domains.wages.getProcessSummary(processMonth.value)
        processData.value = r
      } catch(e) { showToast("加载工序分析失败","error") }
      finally { processLoading.value = false }
    }

    // --- compare state ---
    const compareData = ref([])
    const compareLoading = ref(false)
    const compareMonthA = ref(new Date(new Date().getFullYear(),new Date().getMonth()-1,1).toISOString().slice(0,7))
    const compareMonthB = ref(new Date().toISOString().slice(0,7))

    async function loadCompare() {
      if (!compareMonthA.value || !compareMonthB.value) { showToast("请选择两个月份","error"); return }
      compareLoading.value = true
      try {
        const [rA,rB] = await Promise.all([
          api.domains.wages.getMonthlySummary({ year_month: compareMonthA.value, page: 1, limit: 2000 }),
          api.domains.wages.getMonthlySummary({ year_month: compareMonthB.value, page: 1, limit: 2000 })
        ])
        const mapA = {}; const mapB = {}; const nameMap = {}
        for (const s of (rA.summary||[])) { const k = s.employee_no || s.employee_name; mapA[k] = s.total_wage||0; nameMap[k] = s.employee_name }
        for (const s of (rB.summary||[])) { const k = s.employee_no || s.employee_name; mapB[k] = s.total_wage||0; nameMap[k] = s.employee_name }
        const allKeys = new Set([...Object.keys(mapA), ...Object.keys(mapB)])
        const list = []
        for (const key of allKeys) {
          const wageA = mapA[key]||0; const wageB = mapB[key]||0
          const change = wageB - wageA
          const changePct = wageA ? Number(((change/wageA)*100).toFixed(1)) : (wageB>0 ? 999 : 0)
          list.push({ employee_name: nameMap[key] || key, wageA, wageB, change, changePct: Number(changePct) })
        }
        list.sort((a,b)=>Math.abs(b.change)-Math.abs(a.change))
        compareData.value = list
      } catch(e) { showToast("加载对比数据失败","error") }
      finally { compareLoading.value = false }
    }

    // --- trend state ---
    const trendData = ref([])
    const trendLoading = ref(true)
    const trendMonths = ref(6)
    const trendChartRef = ref(null)
    let trendChart = null

    function trendTotal() { return trendData.value.reduce((s,d) => s + (d.total_wage||0), 0) }
    function trendTotalQty() { return trendData.value.reduce((s,d) => s + (d.total_quantity||0), 0) }
    function trendAvg() {
      if (!trendData.value.length) return 0
      return (trendTotal() / trendData.value.length).toFixed(2)
    }

    async function loadTrends() {
      trendLoading.value = true
      try {
        trendData.value = await api.domains.wages.getWageTrends(trendMonths.value) || []
        await nextTick()
        renderTrendChart()
      } catch(e) { showToast("加载趋势失败","error") }
      finally { trendLoading.value = false }
    }

    function renderTrendChart() {
      const el = trendChartRef.value
      if (!el || !trendData.value.length) { if (trendChart) { trendChart.destroy(); trendChart = null } return }
      if (trendChart) trendChart.destroy()
      const labels = trendData.value.map(d => d.year_month)
      const wages = trendData.value.map(d => d.total_wage||0)
      const qty = trendData.value.map(d => d.total_quantity||0)
      trendChart = new Chart(el, {
        type: "line",
        data: {
          labels,
          datasets: [
            { label: "工资总额 (元)", data: wages, borderColor: "#f59e0b", backgroundColor: "rgba(245,158,11,0.1)", yAxisID: "y", tension: 0.3, fill: true, pointRadius: 5, pointHoverRadius: 7 },
            { label: "总件数", data: qty, borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,0.05)", yAxisID: "y1", tension: 0.3, fill: true, pointRadius: 4, pointHoverRadius: 6, borderDash: [5,5] }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: { legend: { position: "top" } },
          scales: {
            y: { type: "linear", position: "left", title: { display: true, text: "工资 (元)" }, ticks: { callback: v => "¥"+v.toLocaleString() } },
            y1: { type: "linear", position: "right", title: { display: true, text: "件数" }, grid: { drawOnChartArea: false } }
          }
        }
      })
    }


    // --- position state ---
    const posData = ref({ summary: [], grand_total_wage: 0 })
    const posLoading = ref(true)
    const posError = ref(null)
    const posMonth = ref(new Date().getFullYear()+"-"+String(new Date().getMonth()+1).padStart(2,"0"))

    function posPercent(wage) {
      if (!posData.value.grand_total_wage) return 0
      return ((wage/posData.value.grand_total_wage)*100).toFixed(1)
    }
    async function loadPosition() {
      posLoading.value = true
      try { posData.value = await api.domains.wages.getPositionSummary(posMonth.value) || {} }
      catch(e) { posError.value = "加载岗位汇总失败: " + (e.message || e); showToast("加载岗位汇总失败","error") }
      finally { posLoading.value = false }
    }

    // --- prediction state ---
    const predData = ref({})
    const predLoading = ref(true)
    const predError = ref(null)
    const predMonths = ref(6)

    async function loadPrediction() {
      predLoading.value = true
      try { predData.value = await api.domains.wages.getWagePrediction(predMonths.value) || {} }
      catch(e) { predError.value = "加载预测失败: " + (e.message || e); showToast("加载预测失败","error") }
      finally { predLoading.value = false }
    }

    function switchTab(tabId) {
      activeTab.value = tabId
      localStorage.setItem('wageActiveTab', tabId)
      if (tabId==="piece") load()
      if (tabId==="monthly" && !monthlyData.value.summary.length) loadMonthly()
      if (tabId==="process" && !processData.value.summary.length) loadProcess()
      if (tabId==="trend" && !trendData.value.length) loadTrends()
      if (tabId==="position" && (!posData.value.summary || !posData.value.summary.length)) loadPosition()
      if (tabId==="predict" && !predData.value.predicted_wage) loadPrediction()
    }

    if (!_instance) { onMounted(() => {
      if (!tabs.value.some(tab => tab.id === activeTab.value)) {
        activeTab.value = tabs.value[0]?.id || 'piece'
      }
      if (activeTab.value === "piece") load()
      _refreshTimer = setInterval(() => { if (activeTab.value === "piece") load() }, 60000)
    }) }
    if (!_instance) { onBeforeUnmount(() => { if (_refreshTimer) clearInterval(_refreshTimer); _instance = null }) }

    _instance = {
      activeTab, tabs, switchTab,
      wages, loading, dateFrom, dateTo, expandedId, includeRework, hideZero, page, limit, total, totalPages,
      fmtMoney, fmtDate, load, toggle, filteredWages, grandTotal, grandQty, exportCSV, prevPage, nextPage,
      printPayslip,
      monthlyData, monthlyLoading, monthlyMonth, monthlyPage, monthlyLimit, monthlyTotal, monthlyTotalPages, monthlyPercent, loadMonthly, exportMonthlyCSV, monthlyPrevPage, monthlyNextPage,
      processData, processLoading, processMonth, processColor, processPercent, barHeight, loadProcess,
      compareData, compareLoading, compareMonthA, compareMonthB, loadCompare,
      trendData, trendLoading, trendMonths, trendChartRef, trendTotal, trendTotalQty, trendAvg, loadTrends,
      posData, posLoading, posError, posMonth, posPercent, loadPosition,
      predData, predLoading, predError, predMonths, loadPrediction
    }
  return _instance
}
