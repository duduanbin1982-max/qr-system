<template>
<div style="padding:var(--space-6)">
  <div class="card"><div class="card-header"><h3>📊 数据分析</h3></div></div>

  <!-- Tab Bar -->
  <div class="tab-bar" style="display:flex;flex-wrap:wrap;gap:0;margin-bottom:var(--space-5);background:var(--bg-hover);border-radius:var(--radius-lg);padding:var(--space-1);overflow-x:auto">
    <div v-for="t in TABS" :key="t.k"
      @click="switchTab(t.k)" style="flex:1;min-width:90px;text-align:center;padding:var(--space-3) 4px;border-radius:var(--radius-md);cursor:pointer;font-size:var(--text-base);line-height:1.5;font-weight:500;transition:all 0.2s"
      :style="{background: tab===t.k?'var(--bg-surface)':'transparent',color: tab===t.k?'var(--primary)':'var(--text-placeholder)',boxShadow: tab===t.k?'0 1px 3px rgba(0,0,0,0.1)':'none'}">
      {{ t.l }}
    </div>
  </div>

  <!-- Filter Bar: worker & quality & matrix -->
  <div v-if="tab==='worker' || tab==='quality' || tab==='matrix'" class="card" style="margin-bottom:var(--space-4)">
    <div class="card-header">
      <h3>{{ TABS.find(t=>t.k===tab)?.l || '' }}</h3>
      <div style="display:flex;gap:var(--space-2);align-items:center">
        <input type="date" class="form-input" v-model="reportStart" style="width:140px">
        <span style="color:var(--text-placeholder)">至</span>
        <input type="date" class="form-input" v-model="reportEnd" style="width:140px">
        <select class="form-input" v-model="filterProduct" @change="loadCurrent" style="width:180px">
          <option value="">全部产品</option>
          <option v-for="p in productOptions" :key="p.code" :value="p.code">{{ p.label }}</option>
        </select>
        <button class="btn btn-primary btn-sm" @click="loadCurrent">查询</button>
      </div>
    </div>
  </div>

  <!-- Tab Content -->
  <DashboardTab v-if="tab==='dashboard'" />
  <TrendTab v-if="tab==='trend'" />
  <WorkerTab v-if="tab==='worker'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="workerKey" />
  <QualityTab v-if="tab==='quality'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="qualityKey" />
  <OrderTab v-if="tab==='order'" />
  <ReworkTab v-if="tab==='rework'" />
  <ModelTab v-if="tab==='model'" />
  <MatrixTab v-if="tab==='matrix'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="matrixKey" />
</div>
</template>

<script>
import DashboardTab from './reports/DashboardTab.vue'
import TrendTab from './reports/TrendTab.vue'
import WorkerTab from './reports/WorkerTab.vue'
import QualityTab from './reports/QualityTab.vue'
import OrderTab from './reports/OrderTab.vue'
import ReworkTab from './reports/ReworkTab.vue'
import ModelTab from './reports/ModelTab.vue'
import MatrixTab from './reports/MatrixTab.vue'
import { useReportsWorkspace } from '@/composables/reports/useReportsWorkspace.js'

export default {
  components: { DashboardTab, TrendTab, WorkerTab, QualityTab, OrderTab, ReworkTab, ModelTab, MatrixTab },
  setup() {
    return useReportsWorkspace()
  }
}
</script>
<style scoped>
@media (max-width: 768px) {
  .tab-bar { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .tab-bar > div { flex: none; min-width: 70px; white-space: nowrap; font-size: 12px !important; padding: 8px 4px !important; }
}
</style>
