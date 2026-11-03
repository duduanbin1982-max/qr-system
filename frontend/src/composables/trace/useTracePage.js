import { ref } from 'vue'
import { useTraceSearch } from '@/composables/useTraceSearch.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useTracePage() {
  const traceCode = ref('')
  const traceMode = ref('serial')
  const { searching, result, search } = useTraceSearch(api.domains.trace)
  const collectionPages = ref({})
  const collectionPerPages = ref({})
  const lastTraceTarget = ref(null)
  const HISTORY_KEY = 'qr_trace_history'
  const HISTORY_LIMIT = 10

  function isValidHistoryItem(item) {
    return Boolean(
      item
      && typeof item === 'object'
      && typeof item.code === 'string'
      && item.code.trim()
      && (item.mode === 'serial' || item.mode === 'order'),
    )
  }

  function readHistory() {
    try {
      const raw = globalThis.localStorage?.getItem(HISTORY_KEY)
      const parsed = JSON.parse(raw || '[]')
      return Array.isArray(parsed)
        ? parsed.filter(isValidHistoryItem).slice(0, HISTORY_LIMIT)
        : []
    } catch {
      return []
    }
  }

  function persistHistory(history) {
    try {
      globalThis.localStorage?.setItem(HISTORY_KEY, JSON.stringify(history))
    } catch {
      // Storage can be disabled or full; tracing remains usable without history.
    }
  }

  const traceHistory = ref(readHistory())

  function saveHistory(code, mode) {
    const history = traceHistory.value.filter(item => item.code !== code || item.mode !== mode)
    history.unshift({ code, mode })
    traceHistory.value = history.slice(0, HISTORY_LIMIT)
    persistHistory(traceHistory.value)
  }

  function rememberPagination(data) {
    const pagination = data?.meta?.pagination || {}
    const nextPages = {}
    const nextPerPages = {}
    for (const [name, item] of Object.entries(pagination)) {
      if (name === 'items' || !item) continue
      nextPages[name] = item.page
      nextPerPages[name] = item.per_page
    }
    collectionPages.value = nextPages
    collectionPerPages.value = nextPerPages
  }

  function searchOptions(code, mode, page) {
    const options = { code, mode, page, perPage: 100 }
    if (mode === 'order' && Object.keys(collectionPages.value).length) {
      options.collectionPages = { ...collectionPages.value }
      options.collectionPerPages = { ...collectionPerPages.value }
    }
    return options
  }

  async function doTrace(requestedPage = 1) {
    const code = traceCode.value.trim()
    if (!code) {
      showToast(traceMode.value === 'serial' ? '请输入产品序列号' : '请输入订单号', 'error')
      return
    }
    const mode = traceMode.value
    const sameTarget = lastTraceTarget.value
      && lastTraceTarget.value.code === code
      && lastTraceTarget.value.mode === mode
    if (!sameTarget) {
      collectionPages.value = {}
      collectionPerPages.value = {}
    }
    const outcome = await search(searchOptions(code, mode, requestedPage))
    if (!outcome.applied) return
    if (outcome.error) {
      showToast(outcome.error.message || '查询失败', 'error')
      return
    }
    lastTraceTarget.value = { code, mode }
    rememberPagination(outcome.data)
    saveHistory(code, mode)
  }

  async function doCollectionTrace({ name, page, perPage } = {}) {
    const code = traceCode.value.trim()
    if (!code || traceMode.value !== 'order' || !name) return
    const itemsPage = result.value?.meta?.pagination?.items?.page
      || result.value?.meta?.page
      || 1
    const nextPages = { ...collectionPages.value, [name]: page }
    const nextPerPages = { ...collectionPerPages.value, [name]: perPage || 100 }
    const outcome = await search({
      code,
      mode: 'order',
      page: itemsPage,
      perPage: result.value?.meta?.pagination?.items?.per_page || 100,
      collectionPages: nextPages,
      collectionPerPages: nextPerPages,
    })
    if (outcome.applied && !outcome.error) rememberPagination(outcome.data)
  }

  function traceTarget(code, mode) {
    traceCode.value = code
    traceMode.value = mode
    doTrace()
  }

  function printReport() {
    window.print()
  }

  return {
    traceCode,
    traceMode,
    searching,
    result,
    traceHistory,
    doTrace,
    doCollectionTrace,
    traceTarget,
    printReport,
  }
}
