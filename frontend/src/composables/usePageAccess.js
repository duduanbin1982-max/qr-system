import { computed, ref } from 'vue'
import { api } from '@/lib/api.js'
import {
  applyPermissionCatalog,
  canOpenPage,
  filterAllowedTabs,
  getLandingPage,
  getSidebarItems,
  resetPermissionCatalog,
} from '@/lib/permissions.js'

const catalogVersion = ref(0)
const catalogLoaded = ref(false)
const catalogLoading = ref(false)

export async function loadPageAccessCatalog(force = false) {
  if (catalogLoading.value) return catalogLoaded.value
  if (catalogLoaded.value && !force) return true
  catalogLoading.value = true
  try {
    const payload = await api.get('/api/permissions')
    applyPermissionCatalog(payload)
    catalogLoaded.value = true
    catalogVersion.value += 1
    return true
  } catch (_) {
    resetPermissionCatalog()
    catalogLoaded.value = false
    catalogVersion.value += 1
    return false
  } finally {
    catalogLoading.value = false
  }
}

export function usePageAccess() {
  const sidebarItems = computed(() => {
    catalogVersion.value
    return getSidebarItems()
  })

  function canOpen(user, page) {
    catalogVersion.value
    return canOpenPage(user, page)
  }

  function landingPage(user) {
    catalogVersion.value
    return getLandingPage(user)
  }

  function filterTabs(tabs, user) {
    catalogVersion.value
    return filterAllowedTabs(tabs, user)
  }

  return {
    sidebarItems,
    catalogLoaded,
    catalogLoading,
    loadPageAccessCatalog,
    canOpen,
    landingPage,
    filterTabs,
  }
}
