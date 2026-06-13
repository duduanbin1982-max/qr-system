// PriceList Component v3 — 产品路线工价管理（路线工序编辑器 + 透视表概览 + 复制 + 默认工价）
import { ref, reactive, onMounted, computed, watch } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { handleApiError } from '../../api.js'
import { can } from '../../auth.js'
import { router } from '../../router.js?v=56'

export default {
  template: '#price-list-template',
  setup() {
    const loading = ref(true)
    const processes = ref([])

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
    const switching = ref(false)

    // 复制

    // 默认工价
    const showDefaultModal = ref(false)
    const defaultPrices = reactive({}) // {process_id: unit_price}
    const defaultCategory = ref('')

    // RBAC 权限
    const canEdit = computed(() => can('prices:edit'))
    const canCreate = computed(() => can('prices:create'))
    const canDelete = computed(() => can('prices:delete'))

    // 透视表
    const processPricesRaw = ref([])
    const pricingCategory = ref('all')
    const showMatrix = ref(false)

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
        const d = await api.get('/api/route-prices/' + routeId)
        routeSteps.value = d.steps || []
        routeStepsByRoute[routeId] = d.steps || []
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
        const res = await api.put('/api/route-prices/' + rid, data)
        showToast(res.message || '保存成功')
        expandedRoute.value = null
        await loadMatrix()
      } catch (e) { showToast(e.message || '保存失败', 'error') }
      finally { saving.value = false }
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

    const productPrices = computed(() => {
      const map = {}
      processPricesRaw.value.forEach(r => {
        const key = r.product_id == null ? 'null' : '' + r.product_id
        if (!map[key]) {
          map[key] = {
            key, product_id: r.product_id,
            product_code: r.product_code || '(通用)',
            prices: {}, price_ids: [],
            effective_date: r.effective_date, hasActive: false
          }
        }
        map[key].prices[r.process_id] = r.unit_price
        map[key].price_ids.push(r.id)
        if (r.effective_date) map[key].effective_date = r.effective_date
        if (r.status === 'active') map[key].hasActive = true
      })
      return Object.values(map)
    })

    // ====== 数据加载 ======
    async function loadStats() { /* counts now computed reactively */ }

    async function loadAllRoutes(category) {
      try {
        const params = {}
        if (category && category !== 'all') params.category = category
        const d = await api.listProcessRoutes(Object.keys(params).length ? params : null)
        allRoutes.value = d.routes || []
      } catch (e) { showToast('加载路线失败: ' + (e.message || '网络错误'), 'error') }
    }

    async function loadMatrix() {
      try {
        let procUrl = '/api/processes'
        if (pricingCategory.value && pricingCategory.value !== 'all')
          procUrl += '?category=' + encodeURIComponent(pricingCategory.value)
        const [procData, priceData] = await Promise.all([
          api.get(procUrl),
          api.get('/api/process-prices')
        ])
        processes.value = procData.processes || []
        let allPrices = priceData.process_prices || []
        if (pricingCategory.value && pricingCategory.value !== 'all') {
          allPrices = allPrices.filter(r =>
            processes.value.some(p => p.id === r.process_id)
          )
        }
        processPricesRaw.value = allPrices
      } catch (e) { showToast(e.message || '加载失败', 'error') }
      finally { loading.value = false }
    }

    async function openDefaults(cat) {
      defaultCategory.value = cat
      try {
        const d = await api.getDefaultPrices(cat)
        const prices = {}
        ;(d.defaults || []).forEach(r => { prices[r.process_id] = r.unit_price })
        Object.keys(defaultPrices).forEach(k => delete defaultPrices[k])
        Object.assign(defaultPrices, prices)
        showDefaultModal.value = true
      } catch (e) { showToast('加载默认工价失败', 'error') }
    }

    async function saveDefaults() {
      try {
        const prices = {}
        let hasAny = false
        Object.entries(defaultPrices).forEach(([pid, val]) => {
          if (val !== '' && val != null && val !== undefined) { prices[pid] = parseFloat(val); hasAny = true }
        })
        if (!hasAny) { showToast('请至少填写一个工序', 'error'); return }
        const res = await api.saveDefaultPrices({ prices })
        showToast(res.message || '保存成功')
        showDefaultModal.value = false
        await loadMatrix()
      } catch (e) { showToast('保存失败: ' + e.message, 'error') }
    }

    // ====== 透视表操作 ======
    async function deleteProductPrices(row) {
      const ids = row.price_ids || []
      if (ids.length === 0) { showToast('没有可删除的工价', 'error'); return }
      if (!confirm('确定删除该产品的所有工价配置吗？此操作不可恢复。')) return
      try {
        await Promise.all(ids.map(id => api.deleteProcessPrice(id)))
        showToast('删除成功')
        await loadMatrix()
      } catch (e) { showToast(e.message || '删除失败', 'error') }
    }

    async function switchCat(cat) {
      if (switching.value) return
      switching.value = true
      if (pricingCategory.value === cat && allRoutes.value.length > 0) return
      pricingCategory.value = cat
      loading.value = true
      await Promise.all([
        loadAllRoutes(cat === 'all' ? null : cat),
        loadMatrix()
      ])
      switching.value = false
    }

    onMounted(async () => {
      try {
        const cat = categoryFromPage(router.page)
        pricingCategory.value = cat
        await Promise.all([loadStats(), loadAllRoutes(cat === 'all' ? null : cat), loadMatrix()])
      } catch (e) {
        showToast('????????: ' + (e.message || '????'), 'error')
      }
    })

    watch(() => router.page, (page) => {
      const cat = categoryFromPage(page)
      if (pricingCategory.value !== cat) { pricingCategory.value = cat; loadAllRoutes(cat === 'all' ? null : cat); loadMatrix() }
    })

    return {
      // 状态
      loading, processes, pricingCategory, productPrices, pageTitle,
      routeSteps, allRoutes, filteredRoutes,
      editPrices, saving,
      showMatrix, showDefaultModal, defaultPrices, defaultCategory,
      totalRouteCount, structRouteCount, machRouteCount, pricedRouteCount,
      can, canEdit, canCreate, canDelete,
      // 卡片模式
      expandedRoute, toggleRoute, editMeta, saveRoute,
      // 方法
      switchCat, loadAllRoutes, loadMatrix, deleteProductPrices,
      openDefaults, saveDefaults
    }
  }
}
