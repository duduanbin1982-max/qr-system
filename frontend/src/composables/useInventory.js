// InventoryList Composable
import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useInventory() {
  const items = ref([])
  const loading = ref(false)
  const total = ref(0)
  
  async function load(params = {}) {
    loading.value = true
    try {
      const d = await api.listInventory(params)
      items.value = d.items || []
      total.value = d.total || 0
    } catch(e) {
      showToast(e.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }
  
  return { items, loading, total, load }
}
