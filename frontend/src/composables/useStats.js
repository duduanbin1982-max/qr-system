// StatsPage Composable
import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useStats() {
  const stats = ref({})
  const loading = ref(false)
  
  async function load(params = {}) {
    loading.value = true
    try {
      const d = await api.getStats(params)
      stats.value = d
    } catch(e) {
      showToast(e.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }
  
  return { stats, loading, load }
}
