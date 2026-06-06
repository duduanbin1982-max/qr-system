// ===== QR-System App Entry =====
import { createApp, ref, onMounted, computed, reactive, watch } from './vendor/vue.esm.js'
import { auth, restoreSession, login, logout } from './auth.js'
import { router, navigate, restoreNavState } from './router.js'
import { store, showToast } from './store.js'
import { api } from './api.js'

// 页面组件（逐页添加）
import LoginPage    from './components/Login.js'
import Dashboard    from './components/dashboard/Dashboard.js'
import OrderList   from './components/orders/OrderList.js'
import PriceList   from './components/prices/PriceList.js'
import RouteList   from './components/routes/RouteList.js'
import ScanReport  from './components/scan/ScanReport.js'
import ShipmentList from './components/shipments/ShipmentList.js'
import StatsPage   from './components/stats/StatsPage.js'
import TracePage   from './components/trace/TracePage.js'
import ApprovalPage from './components/approvals/ApprovalPage.js'
import SettingsPage from './components/settings/SettingsPage.js'
import ReportsPage from './components/reports/ReportsPage.js'
import BoardPage   from './components/board/BoardPage.js'
import CustomerList from './components/customers/CustomerList.js'
import ProductList from './components/products/ProductList.js'
import UserList    from './components/users/UserList.js'
import ProcessList from './components/processes/ProcessList.js'
import InventoryList from './components/inventory/InventoryList.js'

// 模板中通过 A.xxx 访问全局对象
window.A = { auth, router, store, showToast, navigate, login, logout, api }

const app = createApp({
  template: '#app-template',
  
  components: {
    LoginPage,
    Dashboard,
    CustomerList,
    ProductList,
    UserList,
    ProcessList,
    InventoryList,
    OrderList,
    PriceList,
    RouteList,
    ScanReport,
    ShipmentList,
    StatsPage,
    TracePage,
    ApprovalPage,
    SettingsPage,
    ReportsPage,
    BoardPage,
  },
  setup() {
    const ready = ref(false)

    // 子菜单展开状态
    const menuOpen = reactive({})

    function toggleMenu(key) {
      menuOpen[key] = !menuOpen[key]
    }

    function isMenuActive(item) {
      const page = router.page
      if (item.page === page) return true
      if (item.children) {
        return item.children.some(c => c.page === page)
      }
      return false
    }
    
    // 计算当前视图组件名
    const currentView = computed(() => {
      const page = router.page
      const map = {
        'login': 'LoginPage',
        'dashboard': 'Dashboard',
        'customers': 'CustomerList',
        'orders': 'OrderList',
        'products': 'ProductList',
        'all-products': 'ProductList',
        'structure-products': 'ProductList',
        'machining-products': 'ProductList',
        'users': 'UserList',
        'processes': 'ProcessList',
        'all-processes': 'ProcessList',
        'structure-processes': 'ProcessList',
        'machining-processes': 'ProcessList',
        'inventory': 'InventoryList',
        'prices': 'PriceList',
        'all-prices': 'PriceList',
        'structure-prices': 'PriceList',
        'machining-prices': 'PriceList',
        'routes': 'RouteList',
        'scan': 'ScanReport',
        'shipments': 'ShipmentList',
        'stats': 'StatsPage',
        'trace': 'TracePage',
        'approvals': 'ApprovalPage',
        'settings': 'SettingsPage',
        'reports': 'ReportsPage',
        'board': 'BoardPage',
      }
      return map[page] || 'Dashboard'
    })
    
    // 侧边栏菜单（支持二级子菜单 + 权限控制）
    const sidebarItems = [
      { page: 'dashboard', icon: '📊', label: '工作台',       required: null },
      { page: 'orders',    icon: '📋', label: '订单管理',     required: 'orders:view' },
      { page: 'scan',      icon: '📱', label: '扫码报工',     required: 'scan:view' },
      { page: 'processes', icon: '⚙️', label: '工序管理',     required: 'processes:view', children: [
        { page: 'all-processes',       icon: '📋', label: '全部工序',   required: 'processes:view' },
        { page: 'structure-processes', icon: '🔩', label: '结构件工序', required: 'processes:view' },
        { page: 'machining-processes', icon: '⚙️', label: '机加工工序', required: 'processes:view' },
      ]},
      { page: 'routes',    icon: '🔀', label: '工序路线',     required: 'routes:view' },
      { page: 'users',     icon: '👥', label: '员工管理',     required: 'users:view' },
      { page: 'prices',    icon: '💰', label: '工价管理',     required: 'prices:view' },
      { page: 'products',  icon: '🏭', label: '产品管理',     required: 'products:view', children: [
        { page: 'all-products',       icon: '📋', label: '全部产品',   required: 'products:view' },
        { page: 'structure-products', icon: '🔩', label: '结构件产品', required: 'products:view' },
        { page: 'machining-products', icon: '⚙️', label: '机加工产品', required: 'products:view' },
      ]},
      { page: 'customers', icon: '🏢', label: '客户管理',     required: 'customers:view' },
      { page: 'inventory', icon: '🏗️', label: '库存管理',     required: 'inventory:view' },
      { page: 'shipments', icon: '🚚', label: '发货管理',     required: 'shipments:view' },
      { page: 'stats',     icon: '📈', label: '统计报表',     required: 'stats:view' },
      { page: 'trace',     icon: '🔍', label: '产品追溯',     required: 'trace:view' },
      { page: 'approvals', icon: '✅', label: '审批管理',     required: 'approvals:view' },
      { page: 'board',     icon: '📺', label: '数据看板',     required: 'board:view' },
      { page: 'reports',   icon: '📊', label: '数据分析',     required: 'reports:view' },
      { page: 'settings',  icon: '⚙️', label: '系统设置',     required: 'settings:manage' },
    ]

    // 根据用户权限过滤可见菜单
    function hasPerm(perm) {
      if (!perm) return true  // null = 所有人可见
      const perms = auth.user?.permissions || []
      if (perms.includes('*')) return true
      return perms.includes(perm)
    }

    const visibleSidebar = computed(() =>
      sidebarItems.filter(item => {
        if (!hasPerm(item.required)) return false
        // 过滤子菜单
        if (item.children) {
          const visible = item.children.filter(c => hasPerm(c.required))
          return visible.length > 0
        }
        return true
      }).map(item => {
        if (item.children) return {
          ...item,
          children: item.children.filter(c => hasPerm(c.required))
        }
        return item
      })
    )
    
    // 页面切换时自动展开对应子菜单
    watch(() => router.page, (page) => {
      for (const item of visibleSidebar.value) {
        if (item.children && item.children.some(c => c.page === page)) {
          menuOpen[item.page] = true
        }
      }
    })
    
    onMounted(async () => {
      if (restoreSession()) {
        restoreNavState()
        const saved = localStorage.getItem('currentPage')
        if (saved && saved !== 'login') router.page = saved
        else router.page = 'dashboard'
      }
      ready.value = true
      store.loading = false
    })
    
    return { ready, currentView, sidebarItems, visibleSidebar, menuOpen, toggleMenu, isMenuActive }
  }
})

app.config.globalProperties.A = { auth, router, store, showToast, navigate, login, logout, api }

app.mount('#app')
