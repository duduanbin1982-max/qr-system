import { computed, ref } from 'vue'


export function useOrderFormSearch({ form, products, processRoutes }) {
  const productSearch = ref('')
  const showProductDropdown = ref(false)
  const productSearchResults = ref([])
  const recentProducts = ref([])
  const productCursor = ref(-1)
  const routeSearch = ref('')
  const showRouteDropdown = ref(false)
  const routeCursor = ref(-1)

  const filteredRoutes = computed(() => {
    const keyword = (routeSearch.value || '').trim().toLowerCase()
    if (!keyword) return processRoutes.value
    return processRoutes.value.filter(route => (route.name || '').toLowerCase().includes(keyword))
  })

  function onRouteSearchFocus() {
    showRouteDropdown.value = true
    routeCursor.value = -1
  }

  function onRouteSearchInput() {
    routeCursor.value = filteredRoutes.value.length ? 0 : -1
  }

  function moveRouteCursor(direction) {
    if (!filteredRoutes.value.length) return
    routeCursor.value = Math.min(
      Math.max(routeCursor.value + direction, 0),
      filteredRoutes.value.length - 1,
    )
  }

  function selectRouteByEnter() {
    if (routeCursor.value >= 0 && routeCursor.value < filteredRoutes.value.length) {
      selectRoute(filteredRoutes.value[routeCursor.value])
    }
  }

  function clearRouteSearch() {
    routeSearch.value = ''
    routeCursor.value = -1
    form.value.route_id = ''
  }

  function selectRoute(route) {
    form.value.route_id = route.id
    routeSearch.value = route.name || ''
    showRouteDropdown.value = false
    routeCursor.value = -1
  }

  function syncRoute(routeId, fallbackName = '') {
    const selectedRoute = processRoutes.value.find(route => route.id == routeId)
    routeSearch.value = selectedRoute?.name || fallbackName
  }

  function onProductSearchFocus() {
    showProductDropdown.value = true
    productCursor.value = -1
  }

  let productSearchTimer = null
  function onProductSearchInput() {
    const keyword = (productSearch.value || '').trim().toLowerCase()
    if (!keyword) {
      productSearchResults.value = []
      productCursor.value = -1
      return
    }
    clearTimeout(productSearchTimer)
    productSearchTimer = setTimeout(() => {
      productSearchResults.value = products.value.filter(product => (
        (product.product_code || '').toLowerCase().includes(keyword)
        || (product.product_name || '').toLowerCase().includes(keyword)
      ))
      productCursor.value = productSearchResults.value.length ? 0 : -1
    }, 250)
  }

  function productCursorList() {
    return productSearch.value ? productSearchResults.value : recentProducts.value
  }

  function moveProductCursor(direction) {
    const list = productCursorList()
    if (!list.length) return
    productCursor.value = Math.min(Math.max(productCursor.value + direction, 0), list.length - 1)
  }

  function selectProductByEnter() {
    const list = productCursorList()
    if (productCursor.value >= 0 && productCursor.value < list.length) {
      selectProduct(list[productCursor.value])
    }
  }

  function clearProductSearch() {
    productSearch.value = ''
    productSearchResults.value = []
    productCursor.value = -1
  }

  function selectProduct(product) {
    const fields = [
      'product_code', 'product_name', 'model', 'spec', 'style',
      'upper_opening', 'plate_thickness', 'category', 'route_id',
    ]
    fields.forEach(field => { form.value[field] = product[field] || '' })
    if (product.price) form.value.price = product.price
    if (product.weight) form.value.weight = product.weight
    productSearch.value = product.product_code || ''
    syncRoute(product.route_id)
    showProductDropdown.value = false
    productCursor.value = -1
    const existingIndex = recentProducts.value.findIndex(item => item.id === product.id)
    if (existingIndex >= 0) recentProducts.value.splice(existingIndex, 1)
    recentProducts.value.unshift(product)
    if (recentProducts.value.length > 5) recentProducts.value.pop()
  }

  function resetSearch() {
    productSearch.value = ''
    routeSearch.value = ''
    showProductDropdown.value = false
    showRouteDropdown.value = false
    productSearchResults.value = []
    productCursor.value = -1
    routeCursor.value = -1
  }

  return {
    productSearch, showProductDropdown, productSearchResults, recentProducts, productCursor,
    routeSearch, showRouteDropdown, routeCursor, filteredRoutes,
    onRouteSearchFocus, onRouteSearchInput, moveRouteCursor, selectRouteByEnter,
    clearRouteSearch, selectRoute, syncRoute,
    onProductSearchFocus, onProductSearchInput, moveProductCursor, selectProductByEnter,
    clearProductSearch, selectProduct, resetSearch,
  }
}
