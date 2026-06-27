import { computed } from 'vue'
import {
  canOpenPage,
  filterAllowedTabs,
  getLandingPage,
  getSidebarItems,
} from '@/lib/permissions.js'
import {
  catalogLoaded,
  catalogLoading,
  catalogVersion,
  loadPageAccessCatalog,
} from '@/lib/permissionCatalog.js'

export { loadPageAccessCatalog } from '@/lib/permissionCatalog.js'

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
