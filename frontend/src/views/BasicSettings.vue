<!-- BasicSettings.vue -->
<template>
<div style="padding:var(--space-6)">
    <h2 style="margin:0 0 16px 0;font-size:var(--text-2xl);font-weight:600">⚙️ 基础设置</h2>
    <!-- Tab bar -->
    <div style="display:flex;gap:var(--space-1);margin-bottom:var(--space-5);border-bottom:2px solid var(--border-light);padding-bottom:0;overflow-x:auto">
      <button v-for="t in tabs" :key="t.key"
        class="tab-btn" :class="{active: activeTab===t.key}"
        @click="switchTab(t.key)">
        {{ t.label }}
      </button>
    </div>

    <!-- Tab content: render each component in its own container, all kept alive via v-show -->
    <div v-show="activeTab==='users'"     style="margin:-16px -24px"><UserList     v-if="loaded.users" /></div>
    <div v-show="activeTab==='processes'" style="margin:-16px -24px"><ProcessList  v-if="loaded.processes" /></div>
    <div v-show="activeTab==='routes'"    style="margin:-16px -24px"><RouteList    v-if="loaded.routes" /></div>
    <div v-show="activeTab==='prices'"    style="margin:-16px -24px"><PriceList    v-if="loaded.prices" /></div>
    <div v-show="activeTab==='products'"  style="margin:-16px -24px"><ProductList  v-if="loaded.products" /></div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import UserList     from './UserList.vue'
import ProcessList  from './ProcessList.vue'
import RouteList    from './RouteList.vue'
import PriceList    from './PriceList.vue'
import ProductList  from './ProductList.vue'

export default {
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
</script>
