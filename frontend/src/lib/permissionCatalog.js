import { ref } from 'vue'
import { request } from './api/client.js'
import {
  applyPermissionCatalog,
  resetPermissionCatalog,
} from './permissions.js'

export const catalogVersion = ref(0)
export const catalogLoaded = ref(false)
export const catalogLoading = ref(false)

let catalogLoadPromise = null

export async function loadPageAccessCatalog(force = false) {
  if (catalogLoading.value && catalogLoadPromise) return catalogLoadPromise
  if (catalogLoaded.value && !force) return true
  catalogLoading.value = true
  catalogLoadPromise = (async () => {
    try {
      const payload = await request('GET', '/api/permissions')
      applyPermissionCatalog(payload)
      catalogLoaded.value = true
      catalogVersion.value += 1
      return true
    } catch (_) {
      resetPageAccessCatalog()
      return false
    } finally {
      catalogLoadPromise = null
      catalogLoading.value = false
    }
  })()
  return catalogLoadPromise
}

export function resetPageAccessCatalog() {
  resetPermissionCatalog()
  catalogLoaded.value = false
  catalogVersion.value += 1
}
