// ===== QR-System App Entry =====
import { createApp, ref, onMounted, computed, reactive, watch } from './vendor/vue.esm.js'
import { auth, restoreSession, login, logout } from './auth.js'
import { router, navigate, restoreNavState } from './router.js'
import { store, showToast } from './store.js'
import { api } from './api.js'

// 页面组件（逐页添加）
import LoginPage    from './components/Login.js'
import Dashboard    from './components/dashboard/Dashboard.js?v=1'
import OrderList   from './components/orders/OrderList.js?v=1'
import PriceList   from './components/prices/PriceList.js'
import RouteList   from './components/routes/RouteList.js'
import ScanReport  from './components/scan/ScanReport.js?v=1'
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
import MaterialList from './components/materials/MaterialList.js'
import GanttChart   from './components/schedule/GanttChart.js'
import ReworkList   from './components/rework/ReworkList.js'
import InspectionList from './components/quality/InspectionList.js'
import WageList      from './components/wages/WageList.js'

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
    MaterialList,
    GanttChart,
    ReworkList,
    InspectionList,
    WageList,
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

    // 菜单权限映射（从服务器加载，可动态配置）
    const menuPermissionMap = reactive({})
    async function loadMenuPermissionMap() {
      try { const d = await api.get('/api/menu-permissions'); (d.menu_permissions||[]).forEach(m => { menuPermissionMap[m.page] = m.permission }) }
      catch(e) { /* use hardcoded defaults */ }
    }

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
        'materials': 'MaterialList',
        'schedule': 'GanttChart',
        'rework': 'ReworkList',
        'quality': 'InspectionList',
        'wages': 'WageList',
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
      { page: 'processes', icon: '⚙️', label: '工序管理',     required: 'processes:view' },
      { page: 'routes',    icon: '🔀', label: '工序路线',     required: 'routes:view' },
      { page: 'users',     icon: '👥', label: '员工管理',     required: 'users:view' },
      { page: 'prices',    icon: '💰', label: '工价管理',     required: 'prices:view' },
      { page: 'products',  icon: '🏭', label: '产品管理',     required: 'products:view' },
      { page: 'customers', icon: '🏢', label: '客户管理',     required: 'customers:view' },
      { page: 'inventory', icon: '🏗️', label: '库存管理',     required: 'inventory:view' },
      { page: 'materials', icon: '📦', label: '物料管理',     required: 'materials:view' },
      { page: 'shipments', icon: '🚚', label: '发货管理',     required: 'shipments:view' },
      { page: 'stats',     icon: '📈', label: '统计报表',     required: 'stats:view' },
      { page: 'trace',     icon: '🔍', label: '产品追溯',     required: 'trace:view' },
      { page: 'approvals', icon: '✅', label: '审批管理',     required: 'approvals:view' },
      { page: 'board',     icon: '📺', label: '数据看板',     required: 'board:view' },
      { page: 'reports',   icon: '📊', label: '数据分析',     required: 'reports:view' },
      { page: 'schedule',  icon: '📅', label: '生产排程',     required: 'schedule:view' },
      { page: 'rework',    icon: '🔧', label: '返工管理',     required: 'orders:view' },
      { page: 'quality',   icon: '🔍', label: '质量检验',     required: 'orders:view' },
      { page: 'wages',     icon: '💰', label: '工资核算',     required: 'orders:view' },
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
        const required = menuPermissionMap[item.page] || item.required
        if (!hasPerm(required)) return false
        // 过滤子菜单
        if (item.children) {
          const visible = item.children.filter(c => hasPerm(menuPermissionMap[c.page] || c.required))
          return visible.length > 0
        }
        return true
      }).map(item => {
        if (item.children) return {
          ...item,
          children: item.children.filter(c => hasPerm(menuPermissionMap[c.page] || c.required))
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

    // 登录设备管理
    const showSessions = ref(false)
    const sessions = ref([])
    const sessionsLoading = ref(false)

    function parseUA(ua) {
      if (!ua) return '未知设备'
      // 提取浏览器和OS
      const m = ua.match(/\((.*?)\)/)
      const os = m ? m[1].split(';')[0].trim() : ''
      let browser = '浏览器'
      if (ua.includes('Chrome')) browser = 'Chrome'
      else if (ua.includes('Firefox')) browser = 'Firefox'
      else if (ua.includes('Safari')) browser = 'Safari'
      else if (ua.includes('Edg')) browser = 'Edge'
      if (ua.includes('Mobile')) browser = '📱 ' + browser
      else browser = '💻 ' + browser
      return os ? `${browser} / ${os}` : browser
    }

    function formatTimeAgo(ts) {
      if (!ts) return ''
      const d = new Date(ts.replace(' ', 'T'))
      const now = new Date()
      const diff = Math.floor((now - d) / 1000)
      if (diff < 60) return '刚刚'
      if (diff < 3600) return Math.floor(diff / 60) + '分钟前'
      if (diff < 86400) return Math.floor(diff / 3600) + '小时前'
      return Math.floor(diff / 86400) + '天前'
    }

    async function loadSessions() {
      sessionsLoading.value = true
      try {
        const d = await api.listSessions()
        sessions.value = d.sessions || []
      } catch (e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        sessionsLoading.value = false
      }
    }

    async function kickSession(sid) {
      try {
        await api.deleteSession(sid)
        showToast('会话已终止')
        await loadSessions()
      } catch (e) {
        showToast(e.message || '操作失败', 'error')
      }
    }

    // 打开时自动加载
    watch(showSessions, (val) => {
      if (val) loadSessions()
    })
    
    onMounted(async () => {
      if (restoreSession()) {
        await loadMenuPermissionMap()
        restoreNavState()
        const saved = localStorage.getItem('currentPage')
        if (saved && saved !== 'login') router.page = saved
        else router.page = 'dashboard'
      }
      ready.value = true
      store.loading = false
    })
    
    return { ready, currentView, sidebarItems, visibleSidebar, menuOpen, toggleMenu, isMenuActive,
             showSessions, sessions, sessionsLoading, parseUA, formatTimeAgo, kickSession }
  }
})

app.config.globalProperties.A = { auth, router, store, showToast, navigate, login, logout, api }
app.config.globalProperties.Math = Math

app.mount('#app')
