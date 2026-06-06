// TracePage Component — 产品追溯
import { ref } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'

export default {
  template: '#trace-page-template',
  setup() {
    const traceCode = ref('')
    const searching = ref(false)
    const result = ref(null)

    async function doTrace() {
      const code = traceCode.value.trim()
      if (!code) { showToast('请输入产品序列号','error'); return }
      searching.value = true
      try {
        const d = await api.trace(code)
        result.value = d
      } catch(e) {
        showToast(e.message || '查询失败','error')
        result.value = null
      } finally {
        searching.value = false
      }
    }

    return { traceCode, searching, result, doTrace }
  }
}
