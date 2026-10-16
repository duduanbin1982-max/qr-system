import { ref, computed, watchEffect } from 'vue'
import { auth } from '@/lib/auth.js'
import { usePageAccess } from '@/composables/usePageAccess.js'

export function useSettingsWorkspace() {
  const pageAccess = usePageAccess()
  const allTabs = [
    { key:'company-info',    page:'company-info',    label:'\u{1F3E2} \u516C\u53F8\u8D44\u6599',   component: 'CompanyInfo' },
    { key:'admin-users',     page:'admin-users',     label:'\u{1F465} \u7BA1\u7406\u5458\u7BA1\u7406', component: 'AdminUsers' },
    { key:'audit-logs',      page:'audit-logs',      label:'\u{1F4CB} \u64CD\u4F5C\u65E5\u5FD7',     component: 'AuditLogs' },
    { key:'process-config',  page:'process-config',  label:'\u2699\uFE0F \u5DE5\u827A\u7BA1\u7406',   component: 'ProcessConfig' },
    { key:'role-groups',     page:'role-groups',     label:'\u{1F454} \u89D2\u8272\u7EC4',           component: 'RoleGroups' },
    { key:'role-manage',     page:'role-manage',     label:'\u{1F465} \u89D2\u8272\u7BA1\u7406',     component: 'RoleManage' },
    { key:'positions',       page:'positions',       label:'\u{1F4BC} \u5C97\u4F4D\u7BA1\u7406',     component: 'Positions' },
    { key:'approval-config', page:'approval-config', label:'\u2705 \u5BA1\u6279\u914D\u7F6E',         component: 'ApprovalConfig' },
  ]
  const tabs = computed(() => pageAccess.filterTabs(allTabs, auth.user))

  const STORAGE_KEY = 'settingsTab'
  const activeTab = ref(localStorage.getItem(STORAGE_KEY) || 'company-info')
  const activeComponent = ref(null)

  function changeTab(nextTab) {
    if (nextTab === activeTab.value) return
    if (
      activeComponent.value?.hasUnsavedChanges?.()
      && !window.confirm(`${tabs.value.find(t => t.key === activeTab.value)?.label || '当前页面'}有未保存的改动，确定离开吗？`)
    ) return
    activeTab.value = nextTab
  }

  watchEffect(() => {
    if (!tabs.value.length) {
      activeTab.value = ''
      return
    }
    if (!tabs.value.some(t => t.key === activeTab.value)) {
      activeTab.value = tabs.value[0].key
    }
    localStorage.setItem(STORAGE_KEY, activeTab.value)
  })

  const currentComponent = computed(() => {
    const t = tabs.value.find(t => t.key === activeTab.value)
    return t ? t.component : 'CompanyInfo'
  })

  return { tabs, activeTab, activeComponent, currentComponent, changeTab }
}
