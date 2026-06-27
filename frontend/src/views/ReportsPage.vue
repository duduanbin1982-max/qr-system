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
import { ref, onMounted } from 'vue'
import { TABS } from './reports/shared.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import DashboardTab from './reports/DashboardTab.vue'
import TrendTab from './reports/TrendTab.vue'
import WorkerTab from './reports/WorkerTab.vue'
import QualityTab from './reports/QualityTab.vue'
import OrderTab from './reports/OrderTab.vue'
import ReworkTab from './reports/ReworkTab.vue'
import ModelTab from './reports/ModelTab.vue'
import MatrixTab from './reports/MatrixTab.vue'

export default {
  components: { DashboardTab, TrendTab, WorkerTab, QualityTab, OrderTab, ReworkTab, ModelTab, MatrixTab },
  setup() {
    const tab = ref('dashboard')
    const reportStart = ref(''); const reportEnd = ref('')
    const filterProduct = ref(''); const productOptions = ref([])
    const workerKey = ref(0); const qualityKey = ref(0); const reworkKey = ref(0); const matrixKey = ref(0)
    const keyMap = { worker: workerKey, quality: qualityKey, rework: reworkKey, matrix: matrixKey }

    function initDates() {
      const now = new Date()
      const local = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0')
      reportEnd.value = local(now)
      reportStart.value = local(new Date(now - 30*86400000))
    }

    async function loadProducts() {
      try {
        const d = await api.listProducts({limit: 500})
        productOptions.value = (d.products||[]).map(p=>({code:p.product_code,label:p.product_name+' '+p.model}))
      } catch(e) {
        showToast('加载产品列表失败，筛选功能不可用', 'warning')
      }
    }

    function switchTab(t) { tab.value = t }
    function loadCurrent() { if (keyMap[tab.value]) keyMap[tab.value].value++ }

    onMounted(() => { initDates(); loadProducts() })

    return { tab, TABS, reportStart, reportEnd, filterProduct, productOptions, workerKey, qualityKey, reworkKey, matrixKey, switchTab, loadCurrent }
  }
}
</script>
<style scoped>
@media (max-width: 768px) {
  .tab-bar { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .tab-bar > div { flex: none; min-width: 70px; white-space: nowrap; font-size: 12px !important; padding: 8px 4px !important; }
}
</style>
