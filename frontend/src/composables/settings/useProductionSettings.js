import { ref, computed, watchEffect } from 'vue'
import { auth } from '@/lib/auth.js'
import { usePageAccess } from '@/composables/usePageAccess.js'

export function useProductionSettings() {
  const pageAccess = usePageAccess()
  const allTabs = [
    { key: 'orders',     page: 'orders',     label: '📋 订单管理',   component: 'OrderList' },
    { key: 'customers',  page: 'customers',  label: '🏢 客户管理',   component: 'CustomerList' },
    { key: 'materials',  page: 'materials',  label: '📦 物料管理',   component: 'MaterialList' },
    { key: 'trace',      page: 'trace',      label: '🔍 产品追溯',   component: 'TracePage' },
    { key: 'approvals',  page: 'approvals',  label: '✅ 审批管理',   component: 'ApprovalPage' },
    { key: 'schedule',   page: 'schedule',   label: '📅 生产排程',   component: 'GanttChart' },
    { key: 'rework',     page: 'rework',     label: '🔧 返工管理',   component: 'ReworkList' },
    { key: 'quality',    page: 'quality',    label: '🔎 质量检验',   component: 'InspectionList' },
  ]
  const tabs = computed(() => pageAccess.filterTabs(allTabs, auth.user))

  const STORAGE_KEY = 'productionTab'
  const activeTab = ref(localStorage.getItem(STORAGE_KEY) || 'orders')
  const loaded = ref({})

  function switchTab(key) {
    if (!tabs.value.some(t => t.key === key)) return
    activeTab.value = key
    localStorage.setItem(STORAGE_KEY, key)
    loaded.value[key] = true
  }

  watchEffect(() => {
    if (!tabs.value.length) {
      activeTab.value = ''
      return
    }
    if (!tabs.value.some(t => t.key === activeTab.value)) {
      activeTab.value = tabs.value[0].key
      localStorage.setItem(STORAGE_KEY, activeTab.value)
    }
    loaded.value[activeTab.value] = true
  })

  return { tabs, activeTab, loaded, switchTab }
}
