import { ref, computed, onMounted } from 'vue'
import { TABS, TABS_WITH_DATE, TABS_WITH_PRODUCT } from '@/composables/stats/statsTabs.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useStatsWorkspace() {
  function local(d) { return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0') }

  function reportingDayDate(now = new Date()) {
    const result = new Date(now)
    if (result.getHours() < 7) result.setDate(result.getDate() - 1)
    return result
  }

  function defaultDateRange() {
    const now = new Date()
    const reportingDate = reportingDayDate(now)
    return {
      end: local(reportingDate),
      start: local(new Date(reportingDate.getTime() - 30*86400000)),
    }
  }

  const initialDates = defaultDateRange()
  const tab = ref('daily')
  const loading = ref(false)
  const reportStart = ref(initialDates.start)
  const reportEnd = ref(initialDates.end)
  const filterProduct = ref('')
  const productOptions = ref([])
  const queryKey = ref(0)

  const showFilter = computed(() => TABS_WITH_DATE.includes(tab.value))
  const showProductFilter = computed(() => TABS_WITH_PRODUCT.includes(tab.value))
  const currentTabLabel = computed(() => {
    const t = TABS.find(x => x.k === tab.value)
    return t ? t.l : ''
  })

  function setQuickDate(preset) {
    const now = new Date()
    switch(preset) {
      case 'today':
        reportStart.value = local(reportingDayDate(now))
        reportEnd.value = local(reportingDayDate(now))
        break
      case 'week': {
        const d = new Date(now)
        d.setDate(d.getDate() - d.getDay() + (d.getDay() === 0 ? -6 : 1))
        reportStart.value = local(d)
        reportEnd.value = local(now)
        break
      }
      case 'month':
        reportStart.value = local(new Date(now.getFullYear(), now.getMonth(), 1))
        reportEnd.value = local(now)
        break
      case 'lastMonth':
        reportStart.value = local(new Date(now.getFullYear(), now.getMonth()-1, 1))
        reportEnd.value = local(new Date(now.getFullYear(), now.getMonth(), 0))
        break
    }
    doQuery()
  }

  async function loadProducts() {
    try {
      const d = await api.domains.products.listProducts({})
      productOptions.value = (d.products||[]).map(p => ({code:p.product_code, label:p.product_name+' '+p.model}))
    } catch(e) {
      showToast('加载产品列表失败', 'warning')
    }
  }

  function switchTab(t) { tab.value = t }

  function exportPdf() {
    const params = new URLSearchParams({ tab: tab.value })
    if (reportStart.value) params.set('start', reportStart.value)
    if (reportEnd.value) params.set('end', reportEnd.value)
    if (filterProduct.value) params.set('product_code', filterProduct.value)
    window.open('/api/stats/export-pdf?' + params.toString(), '_blank')
  }

  function doQuery() {
    queryKey.value++
  }

  onMounted(loadProducts)

  return {
    TABS, tab, loading, reportStart, reportEnd, filterProduct, productOptions,
    showFilter, showProductFilter, currentTabLabel,
    switchTab, doQuery, queryKey, setQuickDate, exportPdf,
  }
}
