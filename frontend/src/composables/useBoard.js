// useBoard.js — 生产进度看板 Composable
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const COLOR_PALETTE = [
  '#00d4ff', '#a855f7', '#2ecc71', '#ff9f43', '#ff6b6b',
  '#f1c40f', '#1dd1a1', '#7c3aed', '#ff6b9d', '#54a0ff',
  '#5f27cd', '#01a3a4', '#e66767', '#f8a5c2', '#63cdda'
]

const SCROLL_THRESHOLD = 8
const statusText = { pending: '待生产', producing: '生产中', completed: '已完成' }

export function useBoard() {
  const currentTime = ref('')
  const updateTime = ref('')
  const boardCategory = ref('')
  const stats = ref({})
  const today = ref({})
  const orders = ref([])
  const overdueOrders = ref([])
  const processStats = ref([])
  const workerStats = ref([])
  const recentReports = ref([])
  const maxProcessOutput = ref(1)
  const maxWorkerOutput = ref(1)
  let _timer = null, _refreshTimer = null

  const scrollList = computed(() =>
    orders.value.length > SCROLL_THRESHOLD ? [...orders.value, ...orders.value] : orders.value
  )

  function updateClock() {
    const now = new Date()
    currentTime.value = now.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    })
  }

  function switchCategory(cat) { boardCategory.value = cat; loadData() }

  let _loadingData = false
async function loadData() {
  if (_loadingData) return
  _loadingData = true
    try {
      const params = boardCategory.value ? { category: boardCategory.value } : {}
      const data = await api.board(params)
      stats.value = data.stats || {}
      today.value = data.today || {}
      orders.value = data.orders || []
      overdueOrders.value = data.overdue_orders || []
      processStats.value = data.process_stats || []
      workerStats.value = data.worker_stats || []
      recentReports.value = data.recent_reports || []
      updateTime.value = data.update_time || new Date().toLocaleString('zh-CN')
      maxProcessOutput.value = Math.max(...processStats.value.map(p => p.output || 0), 1)
      maxWorkerOutput.value = Math.max(...workerStats.value.map(w => w.output || 0), 1)
    } catch(e) { showToast(e.message, 'error') }
  }

  function getProcessPercent(item) {
    return maxProcessOutput.value && item.output ? Math.max((item.output / maxProcessOutput.value) * 100, 5) : 0
  }
  function getWorkerPercent(w) {
    return maxWorkerOutput.value && w.output ? Math.max((w.output / maxWorkerOutput.value) * 100, 5) : 0
  }
  function workerBarColor(idx) { return COLOR_PALETTE[idx % COLOR_PALETTE.length] }
  function procBarColor(cat) {
    return cat === '机加工' ? 'linear-gradient(90deg, #a855f7, #7c3aed)' : 'linear-gradient(90deg, #00d4ff, #0090ff)'
  }
  function avatarColor(name) {
    if (!name) return '#00d4ff'
    let hash = 0
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
    return COLOR_PALETTE[Math.abs(hash) % COLOR_PALETTE.length]
  }
  function isOverdue(order) {
    if (!order.plan_end) return false
    const d = new Date()
    const localToday = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
    return order.plan_end < localToday
  }
  function formatTime(timeStr) {
    if (!timeStr) return ''
    const d = new Date(timeStr.replace(/-/g, '/'))
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  }

  onMounted(() => {
    updateClock()
    loadData()
    _timer = setInterval(updateClock, 1000)
    _refreshTimer = setInterval(loadData, 60000)
  })
  onBeforeUnmount(() => {
    if (_timer) clearInterval(_timer)
    if (_refreshTimer) clearInterval(_refreshTimer)
  })

  return {
    currentTime, updateTime, boardCategory, switchCategory,
    stats, today, orders, overdueOrders, processStats, workerStats, recentReports,
    scrollList, statusText, maxProcessOutput, maxWorkerOutput,
    getProcessPercent, getWorkerPercent, workerBarColor, procBarColor,
    avatarColor, isOverdue, formatTime, loadData,
  }
}