import { ref } from 'vue'


export function useTraceSearch(traceApi) {
  const searching = ref(false)
  const result = ref(null)
  let latestRequestId = 0

  async function search({ code, mode, page = 1, perPage = 100 }) {
    const requestId = ++latestRequestId
    searching.value = true
    try {
      const data = mode === 'serial'
        ? await traceApi.trace(code)
        : await traceApi.traceByOrder(code, { page, per_page: perPage })
      if (requestId !== latestRequestId) return { applied: false }
      result.value = data
      return { applied: true, data }
    } catch (error) {
      if (requestId !== latestRequestId) return { applied: false }
      result.value = null
      return { applied: true, error }
    } finally {
      if (requestId === latestRequestId) searching.value = false
    }
  }

  return { result, searching, search }
}
