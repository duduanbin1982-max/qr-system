<!-- WageList.vue — 工资核算模块 -->
<template>
<div class="wage-page">
    <div class="tab-nav wage-tab-nav">
      <button v-for="t in tabs" :key="t.id" @click="switchTab(t.id)"
        :style="{flex:'0 0 auto',whiteSpace:'nowrap',textAlign:'center',padding:'9px 14px',border:'none',borderRadius:'6px',cursor:'pointer',fontSize:'var(--text-sm)',fontWeight:600,transition:'all .2s',background:activeTab===t.id?'#fff':'transparent',color:activeTab===t.id?'var(--primary)':'var(--text-secondary)',boxShadow:activeTab===t.id?'0 1px 3px rgba(0,0,0,.08)':'none'}">
        {{ t.label }}
      </button>
    </div>

    <PayrollLedgerTab v-if="activeTab==='ledger'" />
    <PayrollExceptionsTab v-if="activeTab==='exceptions'" />
    <PriceVersionTab
      v-if="activeTab==='priceversions'"
      :route-version-id="priceIntent.route_version_id"
      :process-version-id="priceIntent.process_version_id"
      :create-intent="priceIntent.create_price"
    />
    <MyPayrollTab v-if="activeTab==='my'" />
    <PieceworkTab v-if="activeTab==='piece'" />
    <MonthlyTab v-if="activeTab==='monthly'" />
    <ProcessWageTab v-if="activeTab==='process'" />
    <CompareTab v-if="activeTab==='compare'" />
    <AdjustmentTab v-if="activeTab==='adjustment'" />
    <TrendTab v-if="activeTab==='trend'" />
    <PositionTab v-if="activeTab==='position'" />
    <PredictTab v-if="activeTab==='predict'" />
</div>
</template>

<script>
import { useWage } from '@/composables/useWage.js'
import PieceworkTab from '@/views/wage/PieceworkTab.vue'
import MonthlyTab from '@/views/wage/MonthlyTab.vue'
import ProcessWageTab from '@/views/wage/ProcessWageTab.vue'
import CompareTab from '@/views/wage/CompareTab.vue'
import AdjustmentTab from '@/views/wage/AdjustmentTab.vue'
import TrendTab from '@/views/wage/TrendTab.vue'
import PositionTab from '@/views/wage/PositionTab.vue'
import PredictTab from '@/views/wage/PredictTab.vue'
import PayrollLedgerTab from '@/views/wage/PayrollLedgerTab.vue'
import PayrollExceptionsTab from '@/views/wage/PayrollExceptionsTab.vue'
import PriceVersionTab from '@/views/wage/PriceVersionTab.vue'
import MyPayrollTab from '@/views/wage/MyPayrollTab.vue'
import { router } from '@/lib/router.js'

export default {
  components: { PayrollLedgerTab, PayrollExceptionsTab, PriceVersionTab, MyPayrollTab, PieceworkTab, MonthlyTab, ProcessWageTab, CompareTab, AdjustmentTab, TrendTab, PositionTab, PredictTab },
  setup() {
    const wage = useWage()
    const params = router.params || {}
    if (params.wage_tab === 'priceversions') wage.switchTab('priceversions')
    return {
      ...wage,
      priceIntent: {
        route_version_id: Number(params.route_version_id) || null,
        process_version_id: Number(params.process_version_id) || null,
        create_price: Boolean(params.create_price),
      },
    }
  }
}
</script>

<style scoped>
.wage-page{width:100%;max-width:100%;min-width:0;padding:var(--space-6);overflow:hidden}.wage-tab-nav{display:flex;max-width:100%;gap:2px;margin-bottom:var(--space-5);padding:4px;overflow-x:auto;overscroll-behavior-x:contain;border-radius:8px;background:var(--bg-secondary);scrollbar-width:thin}@media(max-width:768px){.wage-page{padding:var(--space-4) 12px}.wage-tab-nav{margin-bottom:var(--space-4)}}
</style>
