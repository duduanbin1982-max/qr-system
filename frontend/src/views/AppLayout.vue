<!-- AppLayout.vue -->
<template>
<!-- Login Screen -->
  <div v-if="!A.auth.isLoggedIn" class="login-wrapper">
    <LoginPage />
  </div>

  <!-- Main Layout (authenticated) -->
  <div v-else class="app-layout">
    <nav class="sidebar">
      <div class="sidebar-header">🏭 生产管理系统</div>
      <div class="sidebar-menu">
        <div v-for="item in visibleSidebar" :key="item.page">
          <!-- 无子菜单的普通项 -->
          <div v-if="!item.children"
            class="menu-item"
            :class="{ active: A.router.page === item.page }"
            @click="A.navigate(item.page)">
            <span>{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </div>
          <!-- 有子菜单的展开组 -->
          <div v-else :class="['menu-group', { open: menuOpen[item.page] || isMenuActive(item) }]">
            <div class="menu-parent" @click="toggleMenu(item.page)">
              <span>{{ item.icon }}</span>
              <span>{{ item.label }}</span>
              <span class="arrow">▶</span>
            </div>
            <div class="sub-menu">
              <div v-for="sub in item.children" :key="sub.page"
                class="menu-item"
                :class="{ active: A.router.page === sub.page }"
                @click="A.navigate(sub.page)">
                <span>{{ sub.icon }}</span>
                <span>{{ sub.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="sidebar-footer">
        <div class="sidebar-footer-user">
          👤 {{ A.auth.user?.nickname || A.auth.user?.name || '用户' }}
          <span v-if="A.auth.isAdmin" class="admin-badge">管理员</span>
        </div>
        <div class="sidebar-footer-link" @click="showSessions = true">
          <span>📱</span><span>登录设备</span>
        </div>
        <div class="sidebar-footer-link" @click="A.logout(); A.navigate('login')">
          <span>🚪</span><span>退出登录</span>
        </div>
      </div>
    </nav>
    <main class="main-content">
      <component :is="currentView"></component>
    </main>

    <!-- 登录设备模态框 -->
    <div v-if="showSessions" class="modal-overlay" >
      <div class="modal" style="max-width:480px">
        <div class="modal-header">
          <span>📱 登录设备</span>
          <span class="modal-close" @click="showSessions=false">&times;</span>
        </div>
        <div class="modal-body" style="max-height:400px;overflow-y:auto">
          <div v-if="sessionsLoading" style="text-align:center;padding:var(--space-6);color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else-if="sessions.length === 0" style="text-align:center;padding:var(--space-6);color:var(--text-placeholder)">未找到活跃会话</div>
          <div v-else v-for="s in sessions" :key="s.id" style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover);display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-size:var(--text-sm);font-weight:500">
                {{ parseUA(s.user_agent) }}
                <span v-if="s.is_current" style="color:var(--primary);font-size:var(--text-xs-alt)">· 当前设备</span>
              </div>
              <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">
                {{ s.ip_address }} · {{ formatTimeAgo(s.last_active || s.created_at) }}
              </div>
            </div>
            <button v-if="!s.is_current" class="btn btn-sm" style="background:var(--danger-light);color:var(--danger);font-size:var(--text-xs-alt);padding:var(--space-1) 10px" @click="kickSession(s.id)">踢出</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div class="toast-container">
    <div v-if="A.store.toast.show" 
      class="toast" 
      :class="'toast-' + A.store.toast.type">
      {{ A.store.toast.message }}
    </div>
  </div>
</template>

<script>
import { auth, restoreSession, logout } from '@/lib/auth.js'
import { router, navigate, restoreNavState } from '@/lib/router.js'
import { store, showToast } from '@/lib/store.js'
import { api } from '@/lib/api.js'
import { ref, onMounted, computed, reactive, watch } from 'vue'
import LoginPage from './LoginPage.vue'
import DashboardPage from './DashboardPage.vue'
import CustomerList from './CustomerList.vue'
import ProductList from './ProductList.vue'
import UserList from './UserList.vue'
import ProcessList from './ProcessList.vue'
import InventoryList from './InventoryList.vue'
import MaterialList from './MaterialList.vue'
import OrderList from './OrderList.vue'
import PriceList from './PriceList.vue'
import RouteList from './RouteList.vue'
import ScanReport from './ScanReport.vue'
import ShipmentList from './ShipmentList.vue'
import StatsPage from './StatsPage.vue'
import ReportsPage from './ReportsPage.vue'
import TracePage from './TracePage.vue'
import SettingsPage from './SettingsPage.vue'
import BoardPage from './BoardPage.vue'
import BasicSettings from './BasicSettings.vue'
import ProductionSettings from './ProductionSettings.vue'
import ReworkList from './ReworkList.vue'
import GanttChart from './GanttChart.vue'
import ApprovalPage from './ApprovalPage.vue'
import InspectionList from './InspectionList.vue'
import WageList from './WageList.vue'

// Expose globals for template compatibility
window.A = { auth, router, store, showToast, navigate, logout, api }

export default {
  components: {
    LoginPage,
    DashboardPage,
    CustomerList,
    ProductList,
    UserList,
    ProcessList,
    InventoryList,
    MaterialList,
    OrderList,
    PriceList,
    RouteList,
    ScanReport,
    ShipmentList,
    StatsPage,
    ReportsPage,
    TracePage,
    SettingsPage,
    BoardPage,
    BasicSettings,
    ProductionSettings,
    ReworkList,
    GanttChart,
    ApprovalPage,
    InspectionList,
    WageList
  },
  setup() {
    const ready = ref(false)
    const menuOpen = reactive({})
    const showSessions = ref(false)
    const sessions = ref([])
    const sessionsLoading = ref(false)

    const sidebarItems = [
      { page: 'dashboard', icon: '📊', label: '工作台', required: 'dashboard:view' },
      { page: 'production', icon: '🏭', label: '生产管理', required: 'orders:view' },
      { page: 'scan', icon: '📱', label: '扫码报工', required: 'scan:view' },
      { page: 'inventory', icon: '🏗️', label: '库存管理', required: 'inventory:view' },
      { page: 'shipments', icon: '🚚', label: '发货管理', required: 'shipments:view' },
      { page: 'stats', icon: '📈', label: '统计报表', required: 'stats:view' },
      { page: 'reports', icon: '📊', label: '数据分析', required: 'reports:view' },
      { page: 'wages', icon: '💰', label: '工资核算', required: 'orders:view' },
      { page: 'basic-settings', icon: '⚙️', label: '基础设置', required: 'settings:manage' },
      { page: 'settings', icon: '⚙️', label: '系统设置', required: 'settings:manage' },
    ]

    function hasPerm(perm) {
      if (!perm) return true
      const perms = auth.user?.permissions || []
      if (perms.includes('*')) return true
      return perms.includes(perm)
    }

    const visibleSidebar = computed(() =>
      sidebarItems.filter(item => hasPerm(item.required))
    )

    function toggleMenu(key) { menuOpen[key] = !menuOpen[key] }

    function isMenuActive(item) {
      return item.page === router.page
    }

    const currentView = computed(() => {
      const map = {
        'login': 'LoginPage', 'dashboard': 'DashboardPage',
        'customers': 'CustomerList', 'orders': 'OrderList',
        'products': 'ProductList', 'all-products': 'ProductList',
        'structure-products': 'ProductList', 'machining-products': 'ProductList',
        'users': 'UserList', 'processes': 'ProcessList',
        'all-processes': 'ProcessList', 'structure-processes': 'ProcessList',
        'machining-processes': 'ProcessList', 'inventory': 'InventoryList',
        'materials': 'MaterialList', 'schedule': 'GanttChart',
        'rework': 'ReworkList', 'quality': 'InspectionList',
        'wages': 'WageList', 'prices': 'PriceList',
        'all-prices': 'PriceList', 'structure-prices': 'PriceList',
        'machining-prices': 'PriceList', 'routes': 'RouteList',
        'scan': 'ScanReport', 'shipments': 'ShipmentList',
        'stats': 'StatsPage', 'trace': 'TracePage',
        'approvals': 'ApprovalPage', 'settings': 'SettingsPage',
        'basic-settings': 'BasicSettings', 'production': 'ProductionSettings',
        'reports': 'ReportsPage', 'board': 'BoardPage',
      }
      return map[router.page] || 'DashboardPage'
    })

    onMounted(async () => {
      if (await restoreSession()) {
        restoreNavState()
        const saved = localStorage.getItem('currentPage')
        if (saved && saved !== 'login') router.page = saved
        else router.page = 'dashboard'
      }
      ready.value = true
      store.loading = false
    })

    const A = { auth, router, store, showToast, navigate, logout, api }
    return {
      A, ready, currentView, visibleSidebar, menuOpen, toggleMenu, isMenuActive,
      showSessions, sessions, sessionsLoading, auth, router, navigate, logout, store
    }
  }
}
</script>
