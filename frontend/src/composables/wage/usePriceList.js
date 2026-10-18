import { ref, reactive, onMounted, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
import { navigate, router } from '@/lib/router.js'

export function usePriceList() {
  const loading = ref(true)
  const routeSteps = ref([])
  const allRoutes = ref([])
  const totalRouteCount = computed(() => filteredRoutes.value.length)
  const structRouteCount = computed(() => {
    const pool = pricingCategory.value === 'all' ? allRoutes.value : filteredRoutes.value
    return pool.filter(r => r.category === '结构件').length
  })
  const machRouteCount = computed(() => {
    const pool = pricingCategory.value === 'all' ? allRoutes.value : filteredRoutes.value
    return pool.filter(r => r.category === '机加工').length
  })
  const pricedRouteCount = computed(() => {
    return filteredRoutes.value.filter(r => r.priced_route_count > 0).length
  })
  const editPrices = reactive({}) // {process_id: unit_price}
  const saving = ref(false)
  const priceHistory = ref([])
  const switching = ref(false)

  // 复制


  // RBAC 权限
  const canEdit = computed(() => can('prices:edit'))
  const canCreate = computed(() => can('prices:create'))
  const canDelete = computed(() => can('prices:delete'))

  const pricingCategory = ref('all')

  // 按分类筛选产品
  const filteredRoutes = computed(() => {
    if (pricingCategory.value === 'all') return allRoutes.value
    return allRoutes.value.filter(r => r.category === pricingCategory.value)
  })

  // ====== 路线卡片模式 ======
  const expandedRoute = ref(null)
  const editMeta = reactive({})  // { route_id: { effectiveDate, remark } }

  async function toggleRoute(routeId) {
    if (expandedRoute.value === routeId) {
      expandedRoute.value = null
      return
    }
    expandedRoute.value = routeId
    // Initialize editMeta for this route (safely via Vue.set-like assignment)
    if (!editMeta[routeId]) {
      editMeta[routeId] = { effectiveDate: '', remark: '' }
    }
    // Ensure reactive access doesn't fail on first render
    if (!editMeta[expandedRoute.value]) {
      editMeta[expandedRoute.value] = { effectiveDate: '', remark: '' }
    }
    // Load route pricing steps
    try {
      const d = await api.domains.pricing.getRoutePricingDetail(routeId)
      routeSteps.value = d.steps || []
      routeStepsByRoute[routeId] = d.steps || []
      loadPriceHistory(routeId)
      // Init editPrices
      const prices = {}
      routeSteps.value.forEach(s => {
        if (s.unit_price != null) prices[s.process_id] = s.unit_price
      })
      Object.keys(editPrices).forEach(k => delete editPrices[k])
      Object.assign(editPrices, prices)
    } catch (e) {
      showToast('加载路线工价失败', 'error')
      expandedRoute.value = null
    }
  }

  function isRecentDate(dateStr) {
    if (!dateStr) return false
    const d = new Date(dateStr)
    const now = new Date()
    const diff = (now - d) / (1000 * 60 * 60 * 24)
    return diff <= 7
  }

  async function loadPriceHistory(routeId) {
    try {
      const d = await api.domains.pricing.getRoutePricingHistory(routeId)
      priceHistory.value = d.history || []
    } catch (e) { priceHistory.value = [] }
  }

  const routeStepsByRoute = reactive({})  // { routeId: [...] }

  async function saveRoute() {
    const rid = expandedRoute.value
    if (!rid) return
    saving.value = true
    try {
      const steps = routeStepsByRoute[rid] || []
      const prices = {}
      steps.forEach(s => {
        if (editPrices[s.process_id] != null && editPrices[s.process_id] !== '') {
          prices[s.process_id] = parseFloat(editPrices[s.process_id])
        }
      })
      if (!Object.keys(prices).length) { showToast('请至少填写一个工序的单价', 'error'); saving.value = false; return }
      const meta = editMeta[rid] || {}
      const data = { prices, effective_date: meta.effectiveDate, remark: meta.remark }
      const res = await api.domains.pricing.saveRouteLevelPricing(rid, data)
      showToast(res.message || '保存成功')
      priceHistory.value = []
      expandedRoute.value = null
    loading.value = false
    } catch (e) { showToast(e.message || '保存失败', 'error') }
    finally { saving.value = false }
  }

  function openVersionedPricing() {
    localStorage.setItem('wageActiveTab', 'priceversions')
    navigate('wages')
  }

  const pageTitle = computed(() => {
    const cat = pricingCategory.value
    const cnt = filteredRoutes.value.length
    if (cat === '结构件') return '🔩 结构件工价 (' + cnt + ')'
    if (cat === '机加工') return '⚙️ 机加工工价 (' + cnt + ')'
    return '📋 全部工价路线 (' + cnt + ')'
  })

  // 分类筛选
  function categoryFromPage(page) {
    if (page === 'structure-prices') return '结构件'
    if (page === 'machining-prices') return '机加工'
    return 'all'
  }


  // ====== 数据加载 ======
  async function loadStats() { /* counts now computed reactively */ }

  async function loadAllRoutes(category) {
    try {
      const params = {}
      if (category && category !== 'all') params.category = category
      const d = await api.domains.processRoutes.listProcessRoutes(Object.keys(params).length ? params : null)
      allRoutes.value = d.routes || []
    } catch (e) { showToast('加载路线失败: ' + (e.message || '网络错误'), 'error') }
  }



  // ====== 透视表操作 ======


  async function switchCat(cat) {
    if (switching.value) return
    switching.value = true
    if (pricingCategory.value === cat && allRoutes.value.length > 0) return
    pricingCategory.value = cat
    loading.value = true
    await loadAllRoutes(cat === 'all' ? null : cat)
    loading.value = false
    switching.value = false
  }

  onMounted(async () => {
    try {
      const cat = categoryFromPage(router.page)
      pricingCategory.value = cat
      await loadStats()
      await loadAllRoutes(cat === 'all' ? null : cat)
      loading.value = false
    } catch (e) {
      showToast('加载失败: ' + (e.message || '网络错误'), 'error')
    }
  })

  watch(() => router.page, (page) => {
    const cat = categoryFromPage(page)
    if (pricingCategory.value !== cat) { pricingCategory.value = cat; loadAllRoutes(cat === 'all' ? null : cat); loading.value = false }
  })

  return {
    // 状态
    loading, pricingCategory, pageTitle,
    routeSteps, allRoutes, filteredRoutes,
    editPrices, saving, priceHistory,

    totalRouteCount, structRouteCount, machRouteCount, pricedRouteCount,
    can, canEdit, canCreate, canDelete,
    // 卡片模式
    expandedRoute, toggleRoute, editMeta, saveRoute, openVersionedPricing, isRecentDate, loadPriceHistory,
    // 方法
    switchCat, loadAllRoutes,

  }
}
