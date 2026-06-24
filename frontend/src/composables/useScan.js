// ScanReport Composable
import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useScan() {
  const loading = ref(false)
  
  async function scanCode(code) {
    loading.value = true
    try {
      const d = await api.get('/api/mobile/decode/' + encodeURIComponent(code))
      return d
    } catch(e) {
      showToast(e.message || '扫码失败', 'error')
      return null
    } finally {
      loading.value = false
    }
  }
  
  return { loading, scanCode }
}
