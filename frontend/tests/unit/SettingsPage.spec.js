import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsPage from '@/views/SettingsPage.vue'


const mocks = vi.hoisted(() => ({ dirty: true }))

vi.mock('@/lib/auth.js', () => ({ auth: { user: { permissions: ['*'] } } }))
vi.mock('@/composables/usePageAccess.js', () => ({
  usePageAccess: () => ({ filterTabs: tabs => tabs }),
}))

const DirtyCompanyInfo = defineComponent({
  setup(_, { expose }) {
    expose({ hasUnsavedChanges: () => mocks.dirty })
    return () => null
  },
})


describe('SettingsPage unsaved company profile protection', () => {
  beforeEach(() => {
    mocks.dirty = true
    localStorage.setItem('settingsTab', 'company-info')
  })

  it('keeps the company tab when the user cancels leaving a dirty draft', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(SettingsPage, {
      global: {
        stubs: {
          CompanyInfo: DirtyCompanyInfo,
          AdminUsers: true,
          AuditLogs: true,
          ProcessConfig: true,
          RoleGroups: true,
          RoleManage: true,
          Positions: true,
          ApprovalConfig: true,
        },
      },
    })
    await nextTick()

    wrapper.vm.changeTab('admin-users')
    expect(window.confirm).toHaveBeenCalled()
    expect(wrapper.vm.activeTab).toBe('company-info')
    wrapper.unmount()
  })

  it('allows the tab change after explicit confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(SettingsPage, {
      global: {
        stubs: {
          CompanyInfo: DirtyCompanyInfo,
          AdminUsers: true,
          AuditLogs: true,
          ProcessConfig: true,
          RoleGroups: true,
          RoleManage: true,
          Positions: true,
          ApprovalConfig: true,
        },
      },
    })
    await nextTick()

    wrapper.vm.changeTab('admin-users')
    await nextTick()
    expect(wrapper.vm.activeTab).toBe('admin-users')
    wrapper.unmount()
  })
})
