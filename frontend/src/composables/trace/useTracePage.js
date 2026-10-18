import { ref } from 'vue'
import { useTraceSearch } from '@/composables/useTraceSearch.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useTracePage() {
  const traceCode = ref('')
  const traceMode = ref('serial')
  const { searching, result, search } = useTraceSearch(api.domains.trace)
  const HISTORY_KEY = 'qr_trace_history'
  let storedHistory = []
  try {
    storedHistory = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch {
    storedHistory = []
  }
  const traceHistory = ref(storedHistory)

  function saveHistory(code, mode) {
    const history = traceHistory.value.filter(item => item.code !== code || item.mode !== mode)
    history.unshift({ code, mode })
    traceHistory.value = history.slice(0, 10)
    localStorage.setItem(HISTORY_KEY, JSON.stringify(traceHistory.value))
  }

  async function doTrace(requestedPage = 1) {
    const code = traceCode.value.trim()
    if (!code) {
      showToast(traceMode.value === 'serial' ? '请输入产品序列号' : '请输入订单号', 'error')
      return
    }
    const mode = traceMode.value
    const outcome = await search({ code, mode, page: requestedPage, perPage: 100 })
    if (!outcome.applied) return
    if (outcome.error) {
      showToast(outcome.error.message || '查询失败', 'error')
      return
    }
    saveHistory(code, mode)
  }

  function traceTarget(code, mode) {
    traceCode.value = code
    traceMode.value = mode
    doTrace()
  }

  function printReport() {
    window.print()
  }

  return { traceCode, traceMode, searching, result, traceHistory, doTrace, traceTarget, printReport }
}
