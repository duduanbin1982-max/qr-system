import { ref, computed, watchEffect } from 'vue'
import { auth } from '@/lib/auth.js'
import { usePageAccess } from '@/composables/usePageAccess.js'

export function useBasicSettings() {
  const pageAccess = usePageAccess()
  const allTabs = [
    { key: 'users',     page: 'users',     label: '👥 员工管理', component: 'UserList' },
    { key: 'processes', page: 'processes', label: '⚙️ 工序管理', component: 'ProcessList' },
    { key: 'routes',    page: 'routes',    label: '🔀 工序路线', component: 'RouteList' },
    { key: 'prices',    page: 'prices',    label: '💰 工价管理', component: 'PriceList' },
    { key: 'products',  page: 'products',  label: '🏭 产品管理', component: 'ProductList' },
  ]
  const tabs = computed(() => pageAccess.filterTabs(allTabs, auth.user))

  const STORAGE_KEY = 'basicSettingsTab'
  const activeTab = ref(localStorage.getItem(STORAGE_KEY) || 'users')
  const loaded = ref({})

  function switchTab(key) {
    if (!tabs.value.some(t => t.key === key)) return
    activeTab.value = key
    localStorage.setItem(STORAGE_KEY, key)
    loaded.value[key] = true  // mark as loaded so v-if stays true
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

  const currentComponent = computed(() => {
    const t = tabs.value.find(t => t.key === activeTab.value)
    return t ? t.component : 'UserList'
  })

  return { tabs, activeTab, loaded, switchTab, currentComponent }
}
