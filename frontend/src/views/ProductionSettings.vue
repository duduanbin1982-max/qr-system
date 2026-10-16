<!-- ProductionSettings.vue -->
<template>
<div style="padding:var(--space-6)">
    <h2 style="margin:0 0 16px 0;font-size:var(--text-2xl);font-weight:600">🏭 生产管理</h2>
    <div style="display:flex;gap:var(--space-1);margin-bottom:var(--space-5);border-bottom:2px solid var(--border-light);padding-bottom:0;overflow-x:auto">
      <button v-for="t in tabs" :key="t.key"
        class="tab-btn" :class="{active: activeTab===t.key}"
        @click="switchTab(t.key)">
        {{ t.label }}
      </button>
    </div>

    <div v-if="!tabs.length" class="card"><div class="card-body">当前角色没有生产管理子页面权限。</div></div>
    <div v-show="activeTab==='orders'"     style="margin:-16px -24px"><OrderList      v-if="loaded.orders" /></div>
    <div v-show="activeTab==='customers'"  style="margin:-16px -24px"><CustomerList   v-if="loaded.customers" /></div>
    <div v-show="activeTab==='materials'"  style="margin:-16px -24px"><MaterialList   v-if="loaded.materials" /></div>
    <div v-show="activeTab==='trace'"      style="margin:-16px -24px"><TracePage      v-if="loaded.trace" /></div>
    <div v-show="activeTab==='approvals'"  style="margin:-16px -24px"><ApprovalPage   v-if="loaded.approvals" /></div>
    <div v-show="activeTab==='schedule'"   style="margin:-16px -24px"><GanttChart     v-if="loaded.schedule" /></div>
    <div v-show="activeTab==='rework'"     style="margin:-16px -24px"><ReworkList     v-if="loaded.rework" /></div>
    <div v-show="activeTab==='quality'"    style="margin:-16px -24px"><InspectionList v-if="loaded.quality" /></div>
  </div>
</template>

<script>
import OrderList      from './OrderList.vue'
import CustomerList   from './CustomerList.vue'
import MaterialList   from './MaterialList.vue'
import TracePage      from './TracePage.vue'
import ApprovalPage   from './ApprovalPage.vue'
import GanttChart     from './GanttChart.vue'
import ReworkList     from './ReworkList.vue'
import InspectionList from './InspectionList.vue'
import { useProductionSettings } from '@/composables/settings/useProductionSettings.js'

export default {
  components: { OrderList, CustomerList, MaterialList, TracePage, ApprovalPage, GanttChart, ReworkList, InspectionList },
  setup() {
    return useProductionSettings()
  }
}
</script>
