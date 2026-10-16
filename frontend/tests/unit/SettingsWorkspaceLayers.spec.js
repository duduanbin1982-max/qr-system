import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { auth } from '@/lib/auth.js'
import BasicSettings from '@/views/BasicSettings.vue'
import ProductionSettings from '@/views/ProductionSettings.vue'
import SettingsPage from '@/views/SettingsPage.vue'

vi.mock('@/lib/auth.js', async () => {
  const { reactive } = await import('vue')
  return { auth: reactive({ user: { allowedPages: [] } }), can: () => false }
})
vi.mock('@/composables/usePageAccess.js', () => ({
  usePageAccess: () => ({
    filterTabs: (tabs, user) => tabs.filter(tab => user?.allowedPages?.includes(tab.page)),
  }),
}))

const stubs = Object.fromEntries([
  'UserList', 'ProcessList', 'RouteList', 'PriceList', 'ProductList',
  'OrderList', 'CustomerList', 'MaterialList', 'TracePage', 'ApprovalPage',
  'GanttChart', 'ReworkList', 'InspectionList', 'CompanyInfo', 'AdminUsers',
  'AuditLogs', 'ProcessConfig', 'RoleGroups', 'RoleManage', 'Positions', 'ApprovalConfig',
].map(name => [name, true]))

const shells = [
  { name: 'basic settings', component: BasicSettings, storage: 'basicSettingsTab', first: 'users', second: 'processes', denied: 'routes', message: '当前角色没有基础设置子页面权限' },
  { name: 'production settings', component: ProductionSettings, storage: 'productionTab', first: 'orders', second: 'customers', denied: 'materials', message: '当前角色没有生产管理子页面权限' },
  { name: 'system settings', component: SettingsPage, storage: 'settingsTab', first: 'company-info', second: 'admin-users', denied: 'audit-logs', message: '当前角色没有系统设置子页面权限' },
]

describe.each(shells)('$name permission and saved-tab coordination', shell => {
  beforeEach(() => {
    localStorage.clear()
    auth.user = { allowedPages: [shell.first, shell.second] }
  })

  it('corrects a forbidden saved tab and persists the first permitted tab', () => {
    localStorage.setItem(shell.storage, shell.denied)
    const wrapper = mount(shell.component, { global: { stubs } })

    expect(wrapper.findAll('.tab-btn')).toHaveLength(2)
    expect(wrapper.vm.activeTab).toBe(shell.first)
    expect(localStorage.getItem(shell.storage)).toBe(shell.first)
    wrapper.unmount()
  })

  it('reacts to permission replacement without retaining an inaccessible active tab', async () => {
    localStorage.setItem(shell.storage, shell.second)
    const wrapper = mount(shell.component, { global: { stubs } })
    expect(wrapper.vm.activeTab).toBe(shell.second)

    auth.user = { allowedPages: [shell.first] }
    await nextTick()

    expect(wrapper.findAll('.tab-btn')).toHaveLength(1)
    expect(wrapper.vm.activeTab).toBe(shell.first)
    expect(localStorage.getItem(shell.storage)).toBe(shell.first)
    wrapper.unmount()
  })

  it('renders the no-access state without opening a default page', () => {
    auth.user = { allowedPages: [] }
    const wrapper = mount(shell.component, { global: { stubs } })

    expect(wrapper.findAll('.tab-btn')).toHaveLength(0)
    expect(wrapper.vm.activeTab).toBe('')
    expect(wrapper.text()).toContain(shell.message)
    expect(wrapper.findAllComponents({ name: 'UserList' })).toHaveLength(0)
    expect(wrapper.findAllComponents({ name: 'CompanyInfo' })).toHaveLength(0)
    expect(wrapper.findAllComponents({ name: 'OrderList' })).toHaveLength(0)
    wrapper.unmount()
  })
})

describe.each(shells.slice(0, 2))('$name lazy child retention', shell => {
  it('keeps visited children loaded and ignores a forbidden switch', async () => {
    localStorage.clear()
    auth.user = { allowedPages: [shell.first, shell.second] }
    const wrapper = mount(shell.component, { global: { stubs } })

    expect(wrapper.vm.loaded).toEqual({ [shell.first]: true })
    await wrapper.findAll('.tab-btn')[1].trigger('click')
    expect(wrapper.vm.activeTab).toBe(shell.second)
    expect(wrapper.vm.loaded).toEqual({ [shell.first]: true, [shell.second]: true })
    wrapper.vm.switchTab(shell.denied)
    await nextTick()
    expect(wrapper.vm.activeTab).toBe(shell.second)
    expect(localStorage.getItem(shell.storage)).toBe(shell.second)
    expect(wrapper.vm.loaded[shell.denied]).toBeUndefined()
    wrapper.unmount()
  })
})
