<template>
<div style="padding:var(--space-6)">
  <div class="card"><div class="card-header"><h3>📊 统计报表</h3></div></div>

  <div class="tab-bar" style="display:flex;gap:0;margin-bottom:var(--space-5);background:var(--bg-hover);border-radius:var(--radius-lg);padding:var(--space-1);overflow-x:auto">
    <div v-for="t in TABS" :key="t.k"
      @click="switchTab(t.k)" style="flex:1;text-align:center;padding:var(--space-3) 2px;border-radius:var(--radius-md);cursor:pointer;font-size:var(--text-sm);font-weight:500;transition:all 0.2s"
      :style="{background: tab===t.k?'var(--bg-surface)':'transparent',color: tab===t.k?'var(--primary)':'var(--text-placeholder)',boxShadow: tab===t.k?'0 1px 3px rgba(0,0,0,0.1)':'none'}">
      {{ t.l }}
    </div>
  </div>

  <div v-if="showFilter" class="card" style="margin-bottom:var(--space-4)">
    <div class="card-header">
      <h3>{{ currentTabLabel }}</h3>
      <div class="filter-row" style="display:flex;gap:var(--space-2);align-items:center;flex-wrap:wrap">
        <input type="date" class="form-input" v-model="reportStart" style="width:140px">
        <span style="color:var(--text-placeholder)">至</span>
        <input type="date" class="form-input" v-model="reportEnd" style="width:140px">
        <button class="btn" style="padding:4px 8px;font-size:11px;background:var(--bg-hover);border:1px solid var(--border-light);border-radius:var(--radius-md)" @click="setQuickDate('today')">今日</button>
        <button class="btn" style="padding:4px 8px;font-size:11px;background:var(--bg-hover);border:1px solid var(--border-light);border-radius:var(--radius-md)" @click="setQuickDate('week')">本周</button>
        <button class="btn" style="padding:4px 8px;font-size:11px;background:var(--bg-hover);border:1px solid var(--border-light);border-radius:var(--radius-md)" @click="setQuickDate('month')">本月</button>
        <button class="btn" style="padding:4px 8px;font-size:11px;background:var(--bg-hover);border:1px solid var(--border-light);border-radius:var(--radius-md)" @click="setQuickDate('lastMonth')">上月</button>
        <select v-if="showProductFilter" class="form-input" v-model="filterProduct" style="width:180px">
          <option value="">全部产品</option>
          <option v-for="p in productOptions" :key="p.code" :value="p.code">{{ p.label }}</option>
        </select>
        <button class="btn btn-primary btn-sm" @click="doQuery">查询</button><button class="btn" style="padding:4px 10px;font-size:11px;background:var(--bg-hover);border:1px solid var(--border-light);border-radius:var(--radius-md);margin-left:4px" @click="exportPdf">打印/另存 PDF</button>
      </div>
    </div>
  </div>

  <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>

  <DailyTab v-if="tab==='daily'" :date="reportEnd" :productCode="filterProduct" :key="'daily-'+queryKey" />
  <WorkerTab v-if="tab==='worker'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="'worker-'+queryKey" />
  <ScrapTab v-if="tab==='scrap'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="'scrap-'+queryKey" />
  <ProgressTab v-if="tab==='progress'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="'progress-'+queryKey" />
  <ProductTab v-if="tab==='product'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="'product-'+queryKey" />
  <ShipmentTab v-if="tab==='shipment'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="'shipment-'+queryKey" />
  <MaterialTab v-if="tab==='material'" :start="reportStart" :end="reportEnd" :productCode="filterProduct" :key="'material-'+queryKey" />
  <ModelProcessTab v-if="tab==='matrix'" :start="reportStart" :end="reportEnd" :key="'matrix-'+queryKey" />
  <CustomerTab v-if="tab==='customer'" :start="reportStart" :end="reportEnd" :key="'customer-'+queryKey" />
</div>
</template>

<script>
import DailyTab from './stats/DailyTab.vue'
import WorkerTab from './stats/WorkerTab.vue'
import ScrapTab from './stats/ScrapTab.vue'
import ProgressTab from './stats/ProgressTab.vue'
import ProductTab from './stats/ProductTab.vue'
import ShipmentTab from './stats/ShipmentTab.vue'
import MaterialTab from './stats/MaterialTab.vue'
import ModelProcessTab from './stats/ModelProcessTab.vue'
import CustomerTab from './stats/CustomerTab.vue'
import { useStatsWorkspace } from '@/composables/stats/useStatsWorkspace.js'

export default {
  components: { DailyTab, WorkerTab, ScrapTab, ProgressTab, ProductTab, ShipmentTab, MaterialTab, ModelProcessTab, CustomerTab },
  setup() {
    return useStatsWorkspace()
  }
}
</script>
<style scoped>
@media (max-width: 768px) {
  .tab-bar { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .tab-bar > div { flex: none; min-width: 70px; white-space: nowrap; font-size: 12px !important; padding: 8px 4px !important; }
  .filter-row { flex-wrap: wrap; gap: 4px; }
  .filter-row input { width: 100px !important; font-size: 11px !important; }
  .filter-row select { width: 120px !important; }
}
</style>
