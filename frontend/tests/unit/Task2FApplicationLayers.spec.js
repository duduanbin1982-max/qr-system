import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  changePassword: vi.fn(),
  navigate: vi.fn(),
  requestedNavigation: vi.fn(() => ({})),
  restoreSession: vi.fn().mockResolvedValue(false),
  restoreNavState: vi.fn(),
  loadPageAccessCatalog: vi.fn().mockResolvedValue(undefined),
  showToast: vi.fn(),
  can: vi.fn(() => true),
  scan: vi.fn(),
  report: vi.fn(),
  pendingApprovals: vi.fn(),
  approvalHistory: vi.fn(),
  approvalStats: vi.fn(),
  batchApproval: vi.fn(),
  handleApproval: vi.fn(),
  traceSearch: vi.fn(),
}))

vi.mock('@/lib/auth.js', async () => {
  const { reactive } = await import('vue')
  return {
  auth: reactive({ user: null, isAdmin: false, isLoggedIn: false, loading: false }),
  login: mocks.login,
  changePassword: mocks.changePassword,
  restoreSession: mocks.restoreSession,
  logout: vi.fn(),
  can: mocks.can,
  }
})
vi.mock('@/lib/router.js', async () => {
  const { reactive } = await import('vue')
  return {
  router: reactive({ page: 'login', params: {} }),
  navigate: mocks.navigate,
  requestedNavigation: mocks.requestedNavigation,
  restoreNavState: mocks.restoreNavState,
  }
})
vi.mock('@/lib/permissions.js', () => ({
  canOpenPage: () => true,
  getLandingPage: () => 'dashboard',
}))
vi.mock('@/lib/store.js', async () => {
  const { reactive } = await import('vue')
  return {
  store: reactive({ loading: true, toast: {} }),
  showToast: mocks.showToast,
  }
})
vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      scan: { scan: mocks.scan, report: mocks.report },
      approvals: {
        pendingApprovals: mocks.pendingApprovals,
        approvalHistory: mocks.approvalHistory,
        approvalStats: mocks.approvalStats,
        batchApproval: mocks.batchApproval,
        handleApproval: mocks.handleApproval,
      },
      trace: {},
    },
  },
}))
vi.mock('@/composables/usePageAccess.js', async () => {
  const { ref } = await import('vue')
  return {
  usePageAccess: () => ({
    sidebarItems: ref([]),
    canOpen: () => true,
    landingPage: () => 'dashboard',
  }),
  loadPageAccessCatalog: mocks.loadPageAccessCatalog,
  }
})
vi.mock('@/composables/useTraceSearch.js', async () => {
  const { ref } = await import('vue')
  return {
  useTraceSearch: () => ({
    searching: ref(false),
    result: ref(null),
    search: mocks.traceSearch,
  }),
  }
})

import { useAppLayout } from '@/composables/application/useAppLayout.js'
import { useApprovalPage } from '@/composables/approval/useApprovalPage.js'
import { useLoginPage } from '@/composables/auth/useLoginPage.js'
import { useScanReport } from '@/composables/scan/useScanReport.js'
import { useTracePage } from '@/composables/trace/useTracePage.js'
import LoginPage from '@/views/LoginPage.vue'
import { auth } from '@/lib/auth.js'
import { router } from '@/lib/router.js'

vi.stubGlobal('__APP_VERSION__', 'test')

beforeEach(() => {
  vi.clearAllMocks()
  auth.user = null
  auth.isLoggedIn = false
  router.page = 'login'
  router.params = {}
  localStorage.clear()
})

describe('Task 2F application context composables', () => {
  it('renders the build-time application version through the login composable', () => {
    const wrapper = mount(LoginPage)
    try {
      expect(useLoginPage().appVersion).toBe('test')
      expect(wrapper.get('.login-footer').text()).toBe('vtest · Hanyun')
    } finally {
      wrapper.unmount()
    }
  })

  it('keeps login validation and forced password change behavior', async () => {
    const loginPage = useLoginPage()
    await loginPage.handleSubmit()
    expect(loginPage.error.value).toBe('请输入用户名和密码')

    loginPage.username.value = 'operator'
    loginPage.password.value = 'secret'
    mocks.login.mockResolvedValueOnce({ mustChangePassword: true })
    await loginPage.handleSubmit()
    expect(loginPage.showChangePassword.value).toBe(true)

    loginPage.newPassword.value = 'new-password'
    loginPage.confirmPassword.value = 'new-password'
    mocks.changePassword.mockResolvedValueOnce({})
    await loginPage.handleChangePassword()
    expect(mocks.navigate).toHaveBeenCalledWith('dashboard')
  })

  it('keeps scan reporting process and quantity guards', async () => {
    const scan = useScanReport()
    mocks.scan.mockResolvedValueOnce({
      order: {
        id: 7,
        quantity: 10,
        completed: 4,
        processes: [
          { process_id: 11, normal_reportable: false, max_report_quantity: 2 },
          { process_id: 12, normal_reportable: true, max_report_quantity: 3 },
        ],
      },
      item: { serial_no: 'SN-7' },
    })
    scan.scanCode.value = 'ORDER-7'
    await scan.doScan()

    expect(scan.reportProcess.value).toBe(12)
    expect(scan.reportQty.value).toBe(1)
    expect(scan.pctDone()).toBe(40)

    mocks.report.mockResolvedValueOnce({})
    mocks.scan.mockResolvedValueOnce({ order: scan.order.value, item: { serial_no: 'SN-7' } })
    scan.reportQty.value = 1
    await scan.doReport()
    expect(mocks.report).toHaveBeenCalledWith(expect.objectContaining({ order_id: 7, process_id: 12, quantity: 1, serial_no: 'SN-7' }))
  })

  it('keeps approval filters and selection reset behavior', async () => {
    const approval = useApprovalPage()
    approval.approvals.value = [
      { id: 1, order_no: 'A-100', worker_name: '张三', process_name: '焊接' },
      { id: 2, order_no: 'B-200', worker_name: '李四', process_name: '装配' },
    ]
    approval.filterOrderNo.value = 'A-'
    await nextTick()
    expect(approval.filteredApprovals.value.map(item => item.id)).toEqual([1])
    approval.selectAll.value = true
    approval.toggleSelectAll()
    expect(approval.selectedIds.value).toEqual([1])
    approval.filterOrderNo.value = 'B-'
    await nextTick()
    expect(approval.selectedIds.value).toEqual([])
    expect(approval.selectAll.value).toBe(false)
  })

  it('keeps trace history and newest-search delegation', async () => {
    mocks.traceSearch.mockResolvedValue({ applied: true })
    const trace = useTracePage()
    trace.traceCode.value = 'SN-100'
    await trace.doTrace()
    expect(mocks.traceSearch).toHaveBeenCalledWith({ code: 'SN-100', mode: 'serial', page: 1, perPage: 100 })
    expect(trace.traceHistory.value[0]).toEqual({ code: 'SN-100', mode: 'serial' })
  })

  it('keeps app layout route selection in the application coordinator', async () => {
    const Harness = { setup: () => useAppLayout(), template: '<div />' }
    const wrapper = mount(Harness)
    await nextTick()
    expect(wrapper.vm.currentView).toBe('LoginPage')
    router.page = 'unknown-page'
    await nextTick()
    expect(wrapper.vm.currentView).toBe('NoPermissionPage')
    wrapper.unmount()
  })
})
