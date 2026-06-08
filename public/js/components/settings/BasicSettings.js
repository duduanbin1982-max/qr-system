// BasicSettingsPage — 基础设置（5个子模块：员工/工序/路线/工价/产品）
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'

import UserList     from '../users/UserList.js'
import ProcessList  from '../processes/ProcessList.js'
import RouteList    from '../routes/RouteList.js'
import PriceList    from '../prices/PriceList.js'
import ProductList  from '../products/ProductList.js'

export default {
  template: '#basic-settings-template',
  components: { UserList, ProcessList, RouteList, PriceList, ProductList },
  setup() {
    const tabs = [
      { key: 'users',     label: '👥 员工管理', component: 'UserList' },
      { key: 'processes', label: '⚙️ 工序管理', component: 'ProcessList' },
      { key: 'routes',    label: '🔀 工序路线', component: 'RouteList' },
      { key: 'prices',    label: '💰 工价管理', component: 'PriceList' },
      { key: 'products',  label: '🏭 产品管理', component: 'ProductList' },
    ]

    const STORAGE_KEY = 'basicSettingsTab'
    const activeTab = ref(localStorage.getItem(STORAGE_KEY) || 'users')
    const loaded = ref({})

    function switchTab(key) {
      activeTab.value = key
      localStorage.setItem(STORAGE_KEY, key)
      loaded.value[key] = true  // mark as loaded so v-if stays true
    }

    // Mark initial tab as loaded
    loaded.value[activeTab.value] = true

    const currentComponent = computed(() => {
      const t = tabs.find(t => t.key === activeTab.value)
      return t ? t.component : 'UserList'
    })

    return { tabs, activeTab, loaded, switchTab, currentComponent }
  }
}
