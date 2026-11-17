<!-- WageList.vue — 工资核算模块 -->
<template>
<div class="wage-page">
    <div class="wage-tab-groups wage-tab-nav" aria-label="工资核算导航">
      <section v-for="group in tabGroups" :key="group.id" class="wage-tab-group">
        <h2>{{ group.label }}</h2>
        <div class="tab-nav wage-tab-nav">
          <button v-for="t in group.tabs" :key="t.id" @click="switchTab(t.id)"
            :aria-current="activeTab===t.id ? 'page' : undefined"
            :style="{flex:'0 0 auto',whiteSpace:'nowrap',textAlign:'center',padding:'8px 12px',border:'none',borderRadius:'6px',cursor:'pointer',fontSize:'var(--text-sm)',fontWeight:600,transition:'all .2s',background:activeTab===t.id?'#fff':'transparent',color:activeTab===t.id?'var(--primary)':'var(--text-secondary)',boxShadow:activeTab===t.id?'0 1px 3px rgba(0,0,0,.08)':'none'}">
            {{ t.label }}
          </button>
        </div>
      </section>
    </div>

    <PayrollLedgerTab v-if="activeTab==='ledger'" />
    <PayrollSettlementTab v-if="activeTab==='settlement'" />
    <PayrollExceptionsTab v-if="activeTab==='exceptions'" />
    <PriceVersionTab
      v-if="activeTab==='priceversions'"
      :route-version-id="priceIntent.route_version_id"
      :process-version-id="priceIntent.process_version_id"
      :create-intent="priceIntent.create_price"
    />
    <MyPayrollTab v-if="activeTab==='my'" />
    <PieceworkTab v-if="activeTab==='piece'" />
    <MonthlyTab v-if="activeTab==='monthly'" :tab-active="activeTab" />
    <ProcessWageTab v-if="activeTab==='process'" :tab-active="activeTab" />
    <CompareTab v-if="activeTab==='compare'" :tab-active="activeTab" />
    <AdjustmentTab v-if="activeTab==='adjustment'" />
    <TrendTab v-if="activeTab==='trend'" :tab-active="activeTab" />
    <PositionTab v-if="activeTab==='position'" :tab-active="activeTab" />
    <PredictTab v-if="activeTab==='predict'" :tab-active="activeTab" />
</div>
</template>

<script>
import PieceworkTab from '@/views/wage/PieceworkTab.vue'
import MonthlyTab from '@/views/wage/MonthlyTab.vue'
import ProcessWageTab from '@/views/wage/ProcessWageTab.vue'
import CompareTab from '@/views/wage/CompareTab.vue'
import AdjustmentTab from '@/views/wage/AdjustmentTab.vue'
import TrendTab from '@/views/wage/TrendTab.vue'
import PositionTab from '@/views/wage/PositionTab.vue'
import PredictTab from '@/views/wage/PredictTab.vue'
import PayrollLedgerTab from '@/views/wage/PayrollLedgerTab.vue'
import PayrollSettlementTab from '@/views/wage/PayrollSettlementTab.vue'
import PayrollExceptionsTab from '@/views/wage/PayrollExceptionsTab.vue'
import PriceVersionTab from '@/views/wage/PriceVersionTab.vue'
import MyPayrollTab from '@/views/wage/MyPayrollTab.vue'
import { useWageWorkspace } from '@/composables/wage/useWageWorkspace.js'

export default {
  components: { PayrollLedgerTab, PayrollSettlementTab, PayrollExceptionsTab, PriceVersionTab, MyPayrollTab, PieceworkTab, MonthlyTab, ProcessWageTab, CompareTab, AdjustmentTab, TrendTab, PositionTab, PredictTab },
  setup() {
    return useWageWorkspace()
  }
}
</script>

<style scoped>
.wage-page{width:100%;max-width:100%;min-width:0;padding:var(--space-6);overflow:hidden}.wage-tab-groups{display:flex;gap:10px;align-items:flex-end;margin-bottom:var(--space-5);overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:thin}.wage-tab-group{min-width:max-content}.wage-tab-group h2{margin:0 0 4px;padding:0 4px;color:var(--text-placeholder);font-size:11px;font-weight:700;letter-spacing:0}.wage-tab-nav{display:flex;max-width:100%;gap:2px;padding:4px;border-radius:8px;background:var(--bg-secondary);scrollbar-width:thin}.wage-tab-nav button span{margin-right:4px}@media(max-width:768px){.wage-page{padding:var(--space-4) 12px}.wage-tab-groups{margin-bottom:var(--space-4);align-items:flex-start}}
</style>
