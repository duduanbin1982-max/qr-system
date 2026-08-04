<!-- WageList.vue — 工资核算模块 -->
<template>
<div style="padding:var(--space-6)">
    <div class="tab-nav" style="display:flex;gap:2px;margin-bottom:var(--space-5);background:var(--bg-secondary);border-radius:8px;padding:4px;overflow-x:auto">
      <button v-for="t in tabs" :key="t.id" @click="switchTab(t.id)"
        :style="{flex:'0 0 auto',whiteSpace:'nowrap',textAlign:'center',padding:'9px 14px',border:'none',borderRadius:'6px',cursor:'pointer',fontSize:'var(--text-sm)',fontWeight:600,transition:'all .2s',background:activeTab===t.id?'#fff':'transparent',color:activeTab===t.id?'var(--primary)':'var(--text-secondary)',boxShadow:activeTab===t.id?'0 1px 3px rgba(0,0,0,.08)':'none'}">
        {{ t.label }}
      </button>
    </div>

    <PayrollLedgerTab v-if="activeTab==='ledger'" />
    <PayrollExceptionsTab v-if="activeTab==='exceptions'" />
    <PriceVersionTab v-if="activeTab==='priceversions'" />
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

export default {
  components: { PayrollLedgerTab, PayrollExceptionsTab, PriceVersionTab, MyPayrollTab, PieceworkTab, MonthlyTab, ProcessWageTab, CompareTab, AdjustmentTab, TrendTab, PositionTab, PredictTab },
  setup() {
    return { ...useWage() }
  }
}
</script>
