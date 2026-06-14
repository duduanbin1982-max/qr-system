import { ref, reactive } from 'vue'
import { api, showToast } from '@/lib/store.js'

/**
 * Route card expand/collapse, step editing, price saving, history loading.
 */
export function useRouteCards() {
  const expandedRoute = ref(null)
  const routeSteps = ref([])
  const routeStepsByRoute = reactive({})
  const editPrices = reactive({})
  const editMeta = reactive({})
  const priceHistory = ref([])
  const saving = ref(false)

  function isRecentDate(dateStr) {
    if (!dateStr) return false
    const d = new Date(dateStr)
    const now = new Date()
    const diff = (now - d) / (1000 * 60 * 60 * 24)
    return diff <= 7
  }

  async function loadPriceHistory(routeId) {
    try {
      const d = await api.get('/api/route-prices/' + routeId + '/history')
      priceHistory.value = d.history || []
    } catch (e) { priceHistory.value = [] }
  }

  async function toggleRoute(routeId) {
    if (expandedRoute.value === routeId) {
      expandedRoute.value = null
      return
    }
    expandedRoute.value = routeId
    if (!editMeta[routeId]) {
      editMeta[routeId] = { effectiveDate: '', remark: '' }
    }
    if (!editMeta[expandedRoute.value]) {
      editMeta[expandedRoute.value] = { effectiveDate: '', remark: '' }
    }
    try {
      const d = await api.get('/api/route-prices/' + routeId)
      routeSteps.value = d.steps || []
      routeStepsByRoute[routeId] = d.steps || []
      loadPriceHistory(routeId)
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

  async function saveRoute(loadMatrixFn) {
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
      if (!Object.keys(prices).length) {
        showToast('请至少填写一个工序的单价', 'error')
        saving.value = false
        return
      }
      const meta = editMeta[rid] || {}
      const data = { prices, effective_date: meta.effectiveDate, remark: meta.remark }
      const res = await api.put('/api/route-prices/' + rid, data)
      showToast(res.message || '保存成功')
      priceHistory.value = []
      expandedRoute.value = null
      if (loadMatrixFn) await loadMatrixFn()
    } catch (e) { showToast(e.message || '保存失败', 'error') }
    finally { saving.value = false }
  }

  return {
    expandedRoute, routeSteps, routeStepsByRoute,
    editPrices, editMeta, priceHistory, saving,
    isRecentDate, loadPriceHistory, toggleRoute, saveRoute
  }
}
