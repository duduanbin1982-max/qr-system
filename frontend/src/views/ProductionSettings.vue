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
import { ref, computed } from 'vue'
import OrderList      from './OrderList.vue'
import CustomerList   from './CustomerList.vue'
import MaterialList   from './MaterialList.vue'
import TracePage      from './TracePage.vue'
import ApprovalPage   from './ApprovalPage.vue'
import GanttChart     from './GanttChart.vue'
import ReworkList     from './ReworkList.vue'
import InspectionList from './InspectionList.vue'

export default {
  components: { OrderList, CustomerList, MaterialList, TracePage, ApprovalPage, GanttChart, ReworkList, InspectionList },
  setup() {
    const tabs = [
      { key: 'orders',     label: '📋 订单管理',   component: 'OrderList' },
      { key: 'customers',  label: '🏢 客户管理',   component: 'CustomerList' },
      { key: 'materials',  label: '📦 物料管理',   component: 'MaterialList' },
      { key: 'trace',      label: '🔍 产品追溯',   component: 'TracePage' },
      { key: 'approvals',  label: '✅ 审批管理',   component: 'ApprovalPage' },
      { key: 'schedule',   label: '📅 生产排程',   component: 'GanttChart' },
      { key: 'rework',     label: '🔧 返工管理',   component: 'ReworkList' },
      { key: 'quality',    label: '🔎 质量检验',   component: 'InspectionList' },
    ]

    const STORAGE_KEY = 'productionTab'
    const activeTab = ref(localStorage.getItem(STORAGE_KEY) || 'orders')
    const loaded = ref({})

    function switchTab(key) {
      activeTab.value = key
      localStorage.setItem(STORAGE_KEY, key)
      loaded.value[key] = true
    }

    loaded.value[activeTab.value] = true

    return { tabs, activeTab, loaded, switchTab }
  }
}
</script>
