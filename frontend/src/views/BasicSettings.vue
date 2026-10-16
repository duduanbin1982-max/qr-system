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
    <div v-if="!tabs.length" class="card"><div class="card-body">当前角色没有基础设置子页面权限。</div></div>
    <div v-show="activeTab==='users'"     style="margin:-16px -24px"><UserList     v-if="loaded.users" /></div>
    <div v-show="activeTab==='processes'" style="margin:-16px -24px"><ProcessList  v-if="loaded.processes" /></div>
    <div v-show="activeTab==='routes'"    style="margin:-16px -24px"><RouteList    v-if="loaded.routes" /></div>
    <div v-show="activeTab==='prices'"    style="margin:-16px -24px"><PriceList    v-if="loaded.prices" /></div>
    <div v-show="activeTab==='products'"  style="margin:-16px -24px"><ProductList  v-if="loaded.products" /></div>
  </div>
</template>

<script>
import UserList     from './UserList.vue'
import ProcessList  from './ProcessList.vue'
import RouteList    from './RouteList.vue'
import PriceList    from './PriceList.vue'
import ProductList  from './ProductList.vue'
import { useBasicSettings } from '@/composables/settings/useBasicSettings.js'

export default {
  components: { UserList, ProcessList, RouteList, PriceList, ProductList },
  setup() {
    return useBasicSettings()
  }
}
</script>
