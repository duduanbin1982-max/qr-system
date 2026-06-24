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
import { SIDEBAR_ITEMS, canOpenPage, getLandingPage } from '@/lib/permissions.js'
import { ref, onMounted, computed, reactive, defineAsyncComponent, h } from 'vue'

const CHUNK_LOAD_ERROR_RE = /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk [\dA-Za-z_-]+ failed|ChunkLoadError|error loading dynamically imported module/i
const TRANSIENT_LOAD_ERROR_RE = /fetch|network|timeout|load failed/i

const AsyncPageError = {
  props: {
    error: { type: Object, default: null },
    pageName: { type: String, default: '页面' },
  },
  setup(props) {
    function refreshPage() {
      window.location.reload()
    }

    return () => h('div', { style: 'padding:var(--space-6)' }, [
      h('div', { class: 'card' }, [
        h('div', { class: 'card-header' }, [
          h('h3', `${props.pageName}加载失败`)
        ]),
        h('div', { class: 'card-body', style: 'display:flex;flex-direction:column;gap:var(--space-3);color:var(--text-secondary)' }, [
          h('div', '页面资源可能刚更新，或当前网络导致模块未成功加载。'),
          h('div', { style: 'font-size:var(--text-sm);color:var(--text-placeholder)' }, props.error?.message || '请刷新页面后重试。'),
          h('div', [
            h('button', { class: 'btn btn-primary', onClick: refreshPage }, '刷新页面')
          ])
        ])
      ])
    ])
  }
}

const NoPermissionPage = {
  setup() {
    function goHome() {
      navigate(getLandingPage(auth.user))
    }

    return () => h('div', { style: 'padding:var(--space-6)' }, [
      h('div', { class: 'card' }, [
        h('div', { class: 'card-header' }, [
          h('h3', '无页面访问权限')
        ]),
        h('div', { class: 'card-body', style: 'display:flex;flex-direction:column;gap:var(--space-3);color:var(--text-secondary)' }, [
          h('div', '当前角色未勾选该页面的显示权限，请联系管理员在角色管理中配置 page:* 权限。'),
          h('div', [
            h('button', { class: 'btn btn-primary', onClick: goHome }, '返回可访问页面')
          ])
        ])
      ])
    ])
  }
}

function definePageAsyncComponent(pageName, loader) {
  const reloadKey = `async-page-reload:${pageName}`

  return defineAsyncComponent({
    loader: async () => {
      const mod = await loader()
      try { sessionStorage.removeItem(reloadKey) } catch (_) {}
      return mod
    },
    delay: 120,
    timeout: 20000,
    errorComponent: {
      props: { error: { type: Object, default: null } },
      setup(props) {
        return () => h(AsyncPageError, { error: props.error, pageName })
      }
    },
    onError(error, retry, fail, attempts) {
      const msg = String(error?.message || error || '')
      const isChunkLoadError = CHUNK_LOAD_ERROR_RE.test(msg)
      const isTransientLoadError = TRANSIENT_LOAD_ERROR_RE.test(msg)

      try {
        if (isChunkLoadError && !sessionStorage.getItem(reloadKey)) {
          sessionStorage.setItem(reloadKey, '1')
          showToast(`${pageName}资源已更新，正在自动刷新…`, 'warning')
          window.location.reload()
          return
        }
      } catch (_) {}

      if (isTransientLoadError && attempts < 2) {
        setTimeout(() => retry(), attempts * 500)
        return
      }

      console.error(`[AsyncPage:${pageName}]`, error)
      fail()
    }
  })
}

const LoginPage = definePageAsyncComponent('登录页', () => import('./LoginPage.vue'))
const DashboardPage = definePageAsyncComponent('工作台', () => import('./DashboardPage.vue'))
const CustomerList = definePageAsyncComponent('客户管理', () => import('./CustomerList.vue'))
const ProductList = definePageAsyncComponent('产品管理', () => import('./ProductList.vue'))
const UserList = definePageAsyncComponent('员工管理', () => import('./UserList.vue'))
const ProcessList = definePageAsyncComponent('工序管理', () => import('./ProcessList.vue'))
const InventoryList = definePageAsyncComponent('库存管理', () => import('./InventoryList.vue'))
const MaterialList = definePageAsyncComponent('物料管理', () => import('./MaterialList.vue'))
const OrderList = definePageAsyncComponent('订单管理', () => import('./OrderList.vue'))
const PriceList = definePageAsyncComponent('工价管理', () => import('./PriceList.vue'))
const RouteList = definePageAsyncComponent('工序路线', () => import('./RouteList.vue'))
const ScanReport = definePageAsyncComponent('扫码报工', () => import('./ScanReport.vue'))
const ShipmentList = definePageAsyncComponent('发货管理', () => import('./ShipmentList.vue'))
const StatsPage = definePageAsyncComponent('统计报表', () => import('./StatsPage.vue'))
const ReportsPage = definePageAsyncComponent('数据分析', () => import('./ReportsPage.vue'))
const TracePage = definePageAsyncComponent('产品追溯', () => import('./TracePage.vue'))
const SettingsPage = definePageAsyncComponent('系统设置', () => import('./SettingsPage.vue'))
const BoardPage = definePageAsyncComponent('数据看板', () => import('./BoardPage.vue'))
const BasicSettings = definePageAsyncComponent('基础设置', () => import('./BasicSettings.vue'))
const ProductionSettings = definePageAsyncComponent('生产设置', () => import('./ProductionSettings.vue'))
const ReworkList = definePageAsyncComponent('返工管理', () => import('./ReworkList.vue'))
const GanttChart = definePageAsyncComponent('生产排程', () => import('./GanttChart.vue'))
const ApprovalPage = definePageAsyncComponent('审批管理', () => import('./ApprovalPage.vue'))
const InspectionList = definePageAsyncComponent('质量检验', () => import('./InspectionList.vue'))
const WageList = definePageAsyncComponent('工资核算', () => import('./WageList.vue'))

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
    WageList,
    NoPermissionPage
  },
  setup() {
    const ready = ref(false)
    const menuOpen = reactive({})
    const showSessions = ref(false)
    const sessions = ref([])
    const sessionsLoading = ref(false)

    const visibleSidebar = computed(() =>
      SIDEBAR_ITEMS.filter(item => canOpenPage(auth.user, item.page))
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
        'no-permission': 'NoPermissionPage',
      }
      if (router.page !== 'login' && router.page !== 'no-permission' && !canOpenPage(auth.user, router.page)) {
        return 'NoPermissionPage'
      }
      return map[router.page] || 'NoPermissionPage'
    })

    onMounted(async () => {
      if (await restoreSession()) {
        restoreNavState()
        const saved = localStorage.getItem('currentPage')
        if (saved && saved !== 'login') router.page = saved
        else router.page = getLandingPage(auth.user)
        if (!canOpenPage(auth.user, router.page)) {
          router.page = getLandingPage(auth.user)
        }
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
