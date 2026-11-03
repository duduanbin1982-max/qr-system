import { ref } from 'vue'


export function useTraceSearch(traceApi) {
  const searching = ref(false)
  const result = ref(null)
  let latestRequestId = 0

  async function search({
    code,
    mode,
    page = 1,
    perPage = 100,
    collectionPages = {},
    collectionPerPages = {},
  }) {
    const requestId = ++latestRequestId
    searching.value = true
    try {
      const data = mode === 'serial'
        ? await traceApi.trace(code)
        : await traceApi.traceByOrder(code, {
          page,
          per_page: perPage,
          ...Object.fromEntries(
            Object.entries(collectionPages).map(([name, value]) => [`${name}_page`, value]),
          ),
          ...Object.fromEntries(
            Object.entries(collectionPerPages).map(([name, value]) => [`${name}_per_page`, value]),
          ),
        })
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
