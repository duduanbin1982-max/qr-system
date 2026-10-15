import { ref, onMounted } from 'vue'
import { TABS } from '@/composables/reports/reportTabs.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useReportsWorkspace() {
  const tab = ref('dashboard')
  const reportStart = ref(''); const reportEnd = ref('')
  const filterProduct = ref(''); const productOptions = ref([])
  const workerKey = ref(0); const qualityKey = ref(0); const reworkKey = ref(0); const matrixKey = ref(0)
  const keyMap = { worker: workerKey, quality: qualityKey, rework: reworkKey, matrix: matrixKey }

  function initDates() {
    const now = new Date()
    const local = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0')
    reportEnd.value = local(now)
    reportStart.value = local(new Date(now - 30*86400000))
  }

  async function loadProducts() {
    try {
      const d = await api.domains.products.listProducts({limit: 500})
      productOptions.value = (d.products||[]).map(p=>({code:p.product_code,label:p.product_name+' '+p.model}))
    } catch(e) {
      showToast('加载产品列表失败，筛选功能不可用', 'warning')
    }
  }

  function switchTab(t) { tab.value = t }
  function loadCurrent() { if (keyMap[tab.value]) keyMap[tab.value].value++ }

  onMounted(() => { initDates(); loadProducts() })

  return { tab, TABS, reportStart, reportEnd, filterProduct, productOptions, workerKey, qualityKey, reworkKey, matrixKey, switchTab, loadCurrent }
}
