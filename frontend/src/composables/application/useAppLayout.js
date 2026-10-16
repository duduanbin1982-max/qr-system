import { ref, onMounted, computed, reactive } from 'vue'
import { auth, restoreSession, logout } from '@/lib/auth.js'
import { navigate, requestedNavigation, restoreNavState, router } from '@/lib/router.js'
import { store, showToast } from '@/lib/store.js'
import { api } from '@/lib/api.js'
import { usePageAccess, loadPageAccessCatalog } from '@/composables/usePageAccess.js'

const A = { auth, router, store, showToast, navigate, logout, api }
if (typeof window !== 'undefined') window.A = A

const VIEW_NAMES = {
  login: 'LoginPage', dashboard: 'DashboardPage',
  customers: 'CustomerList', orders: 'OrderList',
  products: 'ProductList', 'all-products': 'ProductList',
  'structure-products': 'ProductList', 'machining-products': 'ProductList',
  users: 'UserList', processes: 'ProcessList',
  'all-processes': 'ProcessList', 'structure-processes': 'ProcessList',
  'machining-processes': 'ProcessList', inventory: 'InventoryList',
  materials: 'MaterialList', schedule: 'GanttChart',
  rework: 'ReworkList', quality: 'QualityManagementPage', 'quality-management': 'QualityManagementPage',
  wages: 'WageList', performance: 'PerformancePage', 'work-time': 'WorkTimePage',
  'process-quality-evaluation': 'ProcessQualityEvaluationPage', prices: 'PriceList',
  'all-prices': 'PriceList', 'structure-prices': 'PriceList',
  'machining-prices': 'PriceList', routes: 'RouteList',
  scan: 'ScanReport', shipments: 'ShipmentList',
  stats: 'StatsPage', trace: 'TracePage',
  approvals: 'ApprovalPage', settings: 'SettingsPage',
  'basic-settings': 'BasicSettings', production: 'ProductionSettings',
  reports: 'ReportsPage', board: 'BoardPage',
  'no-permission': 'NoPermissionPage',
}

export function useAppLayout() {
  const ready = ref(false)
  const menuOpen = reactive({})
  const showSessions = ref(false)
  const sessions = ref([])
  const sessionsLoading = ref(false)
  const pageAccess = usePageAccess()

  const visibleSidebar = computed(() =>
    pageAccess.sidebarItems.value.filter(item => pageAccess.canOpen(auth.user, item.page))
  )

  function toggleMenu(key) { menuOpen[key] = !menuOpen[key] }

  function isMenuActive(item) {
    return item.page === router.page
  }

  const currentView = computed(() => {
    if (router.page !== 'login' && router.page !== 'no-permission' && !pageAccess.canOpen(auth.user, router.page)) {
      return 'NoPermissionPage'
    }
    return VIEW_NAMES[router.page] || 'NoPermissionPage'
  })

  onMounted(async () => {
    if (await restoreSession()) {
      await loadPageAccessCatalog()
      restoreNavState()
      const requested = requestedNavigation()
      if (requested.settingsTab) {
        localStorage.setItem('settingsTab', requested.settingsTab)
      }
      if (requested.wageTab) {
        localStorage.setItem('wageActiveTab', requested.wageTab)
        router.params = {
          ...router.params,
          wage_tab: requested.wageTab,
          route_version_id: requested.routeVersionId,
          process_version_id: requested.processVersionId,
        }
      }
      const saved = localStorage.getItem('currentPage')
      if (requested.page && pageAccess.canOpen(auth.user, requested.page)) {
        router.page = requested.page
      }
      else if (saved === 'quality') {
        localStorage.setItem('currentPage', 'quality-management')
        router.page = 'quality-management'
      }
      else if (saved && saved !== 'login') router.page = saved
      else router.page = pageAccess.landingPage(auth.user)
      if (!pageAccess.canOpen(auth.user, router.page)) {
        router.page = pageAccess.landingPage(auth.user)
      }
    }
    ready.value = true
    store.loading = false
  })

  return {
    A, ready, currentView, visibleSidebar, menuOpen, toggleMenu, isMenuActive,
    showSessions, sessions, sessionsLoading, auth, router, navigate, logout, store
  }
}
