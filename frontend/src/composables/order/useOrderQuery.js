import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'


export function useOrderQuery() {
  const orders = ref([])
  const loading = ref(true)
  const total = ref(0)
  const page = ref(1)
  const limit = ref(20)
  const filterStatus = ref('')
  const archiveFilter = ref('active')
  const searchKeyword = ref('')
  const filterCustomer = ref('')
  const customers = ref([])
  const products = ref([])
  const processRoutes = ref([])
  const productionLines = ref([])
  const expandedId = ref(null)
  const pendingCount = ref(0)
  const producingCount = ref(0)
  const completedCount = ref(0)

  const statusMap = {
    pending: { label: '待生产', cls: 'badge-pending' },
    producing: { label: '生产中', cls: 'badge-warning' },
    completed: { label: '已完成', cls: 'badge-success' },
    cancelled: { label: '已取消', cls: 'badge-danger' },
    paused: { label: '已暂停', cls: 'badge-secondary' },
  }

  const canCreate = computed(() => can('orders:create'))
  const canEdit = computed(() => can('orders:edit'))
  const canDelete = computed(() => can('orders:delete'))
  const canView = computed(() => can('orders:view'))

  function pct(order) {
    const done = (order.completed || 0) + (order.scrapped || 0)
    if (!order.quantity) return 0
    return Math.min(100, Math.round(done / order.quantity * 100))
  }

  function scrapPct(order) {
    if (!order.quantity || !order.scrapped) return 0
    return Math.round(order.scrapped / order.quantity * 100)
  }

  function riskLabel(level) {
    return ({
      none: '无风险',
      low: '低',
      medium: '中',
      high: '高',
      overdue: '已延期',
    })[level] || '低'
  }

  function formatHours(value) {
    if (value === null || value === undefined || value === '') return '-'
    const hours = Number(value)
    if (!Number.isFinite(hours)) return '-'
    if (hours < 24) return `${hours.toFixed(1)} 小时`
    return `${(hours / 24).toFixed(1)} 天`
  }

  function isOverdue(order) {
    if (!order.plan_end) return false
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    return new Date(order.plan_end) < today && order.status !== 'completed'
  }

  async function load() {
    loading.value = true
    try {
      const params = { page: page.value, limit: limit.value, archive: archiveFilter.value }
      if (filterStatus.value) params.status = filterStatus.value
      if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
      if (filterCustomer.value.trim()) params.customer = filterCustomer.value.trim()
      const data = await api.domains.orders.listOrders(params)
      orders.value = data.orders || []
      total.value = data.total || 0
      pendingCount.value = data.pending ?? 0
      producingCount.value = data.producing ?? 0
      completedCount.value = data.completed ?? 0
    } catch (error) {
      showToast(error.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  let searchTimer = null
  function searchAndLoad() { page.value = 1; load() }
  function archiveChange() { page.value = 1; load() }
  function statusChange() { page.value = 1; load() }
  function customerChange() { page.value = 1; load() }
  function debouncedSearch() {
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
  }

  async function loadDropdownData() {
    try {
      const data = await api.domains.production.listProductionLines()
      productionLines.value = data.lines || []
    } catch (error) {
      productionLines.value = []
    }
    try {
      const [customerData, productData, routeData] = await Promise.all([
        api.domains.customers.listCustomers(),
        api.domains.products.listProducts(),
        api.domains.processRoutes.listProcessRoutes(),
      ])
      customers.value = customerData.customers || []
      products.value = productData.products || []
      processRoutes.value = routeData.routes || []
    } catch (error) {
      customers.value = []
      products.value = []
      processRoutes.value = []
    }
  }

  function toggleExpand(id) {
    expandedId.value = expandedId.value === id ? null : id
  }

  function prevPage() {
    if (page.value > 1) {
      page.value--
      load()
    }
  }

  function nextPage() {
    if (page.value * limit.value < total.value) {
      page.value++
      load()
    }
  }

  return {
    orders, loading, total, page, limit, filterStatus, archiveFilter, searchKeyword, filterCustomer,
    customers, products, processRoutes, productionLines, expandedId,
    pendingCount, producingCount, completedCount, statusMap,
    canCreate, canEdit, canDelete, canView,
    pct, scrapPct, riskLabel, formatHours, isOverdue,
    load, loadDropdownData, searchAndLoad, archiveChange, statusChange, customerChange,
    debouncedSearch, toggleExpand, prevPage, nextPage,
  }
}
