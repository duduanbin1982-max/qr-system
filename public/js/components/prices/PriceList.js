// PriceList Component v3 — 产品路线工价管理（路线工序编辑器 + 透视表概览 + 复制 + 默认工价）
import { ref, reactive, onMounted, computed, watch } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { auth, can } from '../../auth.js?v=56'
import { router } from '../../router.js?v=56'

export default {
  template: '#price-list-template',
  setup() {
    const loading = ref(true)
    const products = ref([])
    const processes = ref([])

    // 产品编辑器
    const selectedProductId = ref('')
    const routeSteps = ref([])
    const routeId = ref(null)
    const routeName = ref('')
    const allRoutes = ref([])
    const totalRouteCount = ref(0)
    const structRouteCount = ref(0)
    const machRouteCount = ref(0)
    const editPrices = reactive({}) // {process_id: unit_price}
    const effectiveDate = ref('')
    const remark = ref('')
    const saving = ref(false)

    // 复制
    const showCopyModal = ref(false)
    const copyFromId = ref('')
    const copyOverwrite = ref(true)

    // 默认工价
    const showDefaultModal = ref(false)
    const defaultPrices = reactive({}) // {process_id: unit_price}
    const defaultCategory = ref('')

    // 透视表
    const processPricesRaw = ref([])
    const pricingCategory = ref('all')
    const showMatrix = ref(false)

    // ====== 路线卡片模式 ======
    const expandedRoute = ref(null)
    const editMeta = reactive({})  // { route_id: { effectiveDate, remark } }

    // 后端已按 category 筛选，前端直接透传
    const filteredRoutes = computed(() => allRoutes.value)

    async function toggleRoute(routeId) {
      if (expandedRoute.value === routeId) {
        expandedRoute.value = null
        return
      }
      expandedRoute.value = routeId
      // Initialize editMeta for this route
      if (!editMeta[routeId]) {
        editMeta[routeId] = { effectiveDate: '', remark: '' }
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
      if (cat === '结构件') return '🔩 结构件工价'
      if (cat === '机加工') return '⚙️ 机加工工价'
      return '📋 全部工价路线'
    })

    // 分类筛选
    function categoryFromPage(page) {
      if (page === 'structure-prices') return '结构件'
      if (page === 'machining-prices') return '机加工'
      return 'all'
    }

    const filteredProducts = computed(() => {
      if (pricingCategory.value === 'all') return products.value
      return products.value.filter(p => p.category === pricingCategory.value)
    })

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
    async function loadProducts() {
      try {
        const d = await api.listProducts()
        products.value = d.products || []
      } catch (e) { showToast('加载产品失败', 'warn') }
    }

    async function loadStats() {
      try {
        const d = await api.listProcessRoutes()
        const all = d.routes || []
        totalRouteCount.value = all.length
        structRouteCount.value = all.filter(r => r.category === '结构件').length
        machRouteCount.value = all.filter(r => r.category === '机加工').length
      } catch (e) { /* silent */ }
    }

    async function loadAllRoutes(category) {
      try {
        const params = {}
        if (category && category !== 'all') params.category = category
        const d = await api.listProcessRoutes(Object.keys(params).length ? params : null)
        allRoutes.value = d.routes || []
      } catch (e) { /* silent */ }
    }

    async function loadMatrix() {
      try {
        let procUrl = '/api/processes'
        if (pricingCategory.value !== 'all')
          procUrl += '?category=' + encodeURIComponent(pricingCategory.value)
        const [procData, priceData] = await Promise.all([
          api.get(procUrl),
          api.get('/api/process-prices')
        ])
        processes.value = procData.processes || []
        let allPrices = priceData.process_prices || []
        if (pricingCategory.value !== 'all') {
          allPrices = allPrices.filter(r =>
            processes.value.some(p => p.id === r.process_id)
          )
        }
        processPricesRaw.value = allPrices
      } catch (e) { showToast(e.message || '加载失败', 'error') }
      finally { loading.value = false }
    }

    // ====== 产品路线工价编辑器 ======
    async function selectProduct() {
      const pid = selectedProductId.value
      if (!pid) { routeSteps.value = []; routeId.value = null; routeName.value = ''; return }
      try {
        const d = await api.getRoutePricing(pid)
        routeSteps.value = d.steps || []
        routeId.value = d.route_id
        routeName.value = d.route_name
        allRoutes.value = d.all_routes || []
        // 初始化编辑字段
        const prices = {}
        routeSteps.value.forEach(s => {
          if (s.unit_price != null) prices[s.process_id] = s.unit_price
        })
        Object.keys(editPrices).forEach(k => delete editPrices[k])
        Object.assign(editPrices, prices)
      } catch (e) { showToast(e.message || '加载路线工价失败', 'error') }
    }

    async function saveRoutePricing() {
      saving.value = true
      try {
        const prices = {}
        let hasAny = false
        Object.entries(editPrices).forEach(([processId, val]) => {
          if (val !== '' && val != null && val !== undefined) {
            prices[processId] = parseFloat(val)
            hasAny = true
          }
        })
        if (!hasAny) { showToast('请至少填写一个工序的单价', 'error'); saving.value = false; return }

        const data = { prices, effective_date: effectiveDate.value, remark: remark.value, route_id: routeId.value }
        const res = await api.saveRoutePricing(selectedProductId.value, data)
        showToast(res.message || '保存成功')
        await selectProduct() // 刷新
        await loadMatrix()    // 刷新透视表
      } catch (e) { showToast(e.message || '保存失败', 'error') }
      finally { saving.value = false }
    }

    async function changeRoute(newRouteId) {
      routeId.value = newRouteId
      // 立即保存路线关联
      try {
        await api.saveRoutePricing(selectedProductId.value, { prices: {}, route_id: newRouteId || null })
        await selectProduct()
      } catch (e) { showToast('路线切换失败: ' + e.message, 'error') }
    }

    // ====== 复制工价 ======
    function openCopy() {
      if (!selectedProductId.value) { showToast('请先选择目标产品', 'error'); return }
      copyFromId.value = ''
      showCopyModal.value = true
    }

    async function doCopy() {
      if (!copyFromId.value) { showToast('请选择源产品', 'error'); return }
      try {
        const res = await api.copyPrices({
          from_product_id: parseInt(copyFromId.value),
          to_product_id: parseInt(selectedProductId.value),
          overwrite: copyOverwrite.value
        })
        showToast(res.message || '复制成功')
        showCopyModal.value = false
        await selectProduct()
        await loadMatrix()
      } catch (e) { showToast('复制失败: ' + e.message, 'error') }
    }

    // ====== 默认工价管理 ======
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

    function switchCat(cat) {
      pricingCategory.value = cat
      loading.value = true
      loadAllRoutes(cat === 'all' ? null : cat)
      loadMatrix()
    }

    onMounted(async () => {
      const cat = categoryFromPage(router.page)
      pricingCategory.value = cat
      await Promise.all([loadProducts(), loadStats(), loadAllRoutes(cat === 'all' ? null : cat), loadMatrix()])
    })

    watch(() => router.page, (page) => {
      const cat = categoryFromPage(page)
      if (pricingCategory.value !== cat) { pricingCategory.value = cat; loadAllRoutes(cat === 'all' ? null : cat); loadMatrix() }
    })

    return {
      // 状态
      loading, products, processes, pricingCategory, productPrices, pageTitle,
      selectedProductId, routeSteps, routeId, routeName, allRoutes,
      editPrices, effectiveDate, remark, saving, filteredProducts,
      showMatrix, showCopyModal, copyFromId, copyOverwrite,
      showDefaultModal, defaultPrices, defaultCategory,
      totalRouteCount, structRouteCount, machRouteCount,
      auth, can,
      // 卡片模式
      filteredRoutes, expandedRoute, toggleRoute, editMeta, saveRoute,
      // 方法
      selectProduct, saveRoutePricing, changeRoute,
      switchCat, deleteProductPrices,
      openCopy, doCopy, openDefaults, saveDefaults
    }
  }
}
