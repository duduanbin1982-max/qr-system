// ReportsPage Composable
import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useReports() {
  const data = ref({})
  const loading = ref(false)
  
  async function load(params = {}) {
    loading.value = true
    try {
      const d = await api.getReports(params)
      data.value = d
    } catch(e) {
      showToast(e.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }
  
  return { data, loading, load }
}
