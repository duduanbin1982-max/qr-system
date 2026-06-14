// WageList Composable
import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useWage() {
  const wages = ref([])
  const loading = ref(false)
  const total = ref(0)
  
  async function load(params = {}) {
    loading.value = true
    try {
      const d = await api.getWages(params)
      wages.value = d.wages || []
      total.value = d.total || 0
    } catch(e) {
      showToast(e.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }
  
  return { wages, loading, total, load }
}
