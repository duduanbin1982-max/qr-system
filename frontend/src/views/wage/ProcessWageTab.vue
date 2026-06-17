<!-- ProcessWageTab.vue -->
<template>
<div v-if="activeTab==='process'">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4)">
        <div class="card" style="border-radius:var(--radius-lg);padding:20px">
          <div style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:16px">
            <h3 style="font-size:var(--text-lg);font-weight:700;margin:0">🔧 工序工资分布</h3>
            <input v-model="processMonth" type="month" class="form-input" style="width:150px;font-size:var(--text-sm);margin-left:auto" @change="loadProcess">
          </div>
          <div v-if="processLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <div v-else style="max-height:400px;overflow-y:auto">
            <div v-for="(p,i) in processData.summary" :key="p.process_id||i" style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--bg-hover)">
              <div style="width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:var(--text-xs);font-weight:700;color:#fff" :style="{background:processColor(i)}">{{ i+1 }}</div>
              <div style="flex:1">
                <div style="font-weight:600;font-size:var(--text-sm)">{{ p.process_name }}</div>
                <div style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ p.worker_count }} 人 · {{ p.total_quantity }} 件 · {{ p.category||'' }}</div>
              </div>
              <div style="text-align:right">
                <div style="font-weight:700;color:var(--warning-dark);font-size:var(--text-sm)">¥{{ fmtMoney(p.total_wage) }}</div>
                <div style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ processPercent(p.total_wage) }}%</div>
              </div>
            </div>
          </div>
          <div v-if="!processLoading" style="margin-top:12px;padding-top:12px;border-top:2px solid var(--border-light);display:flex;justify-content:space-between;font-weight:700">
            <span>合计</span><span style="color:var(--warning-dark)">¥{{ fmtMoney(processData.grand_total_wage) }}</span>
          </div>
        </div>
        <div class="card" style="border-radius:var(--radius-lg);padding:20px">
          <h3 style="font-size:var(--text-lg);font-weight:700;margin:0 0 16px">📊 工序产量对比</h3>
          <div v-if="processLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <div v-else style="display:flex;align-items:flex-end;gap:12px;height:280px;padding:0 8px">
            <div v-for="(p,i) in processData.summary" :key="i" style="flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end">
              <div style="font-size:var(--text-xs);font-weight:600;color:var(--text-primary);margin-bottom:4px">{{ p.total_quantity }}</div>
              <div :style="{width:'100%',maxWidth:'60px',height:barHeight(p.total_quantity)+'%',background:processColor(i),borderRadius:'6px 6px 0 0',minHeight:'4px',transition:'height .4s'}"></div>
              <div style="font-size:10px;color:var(--text-placeholder);margin-top:6px;text-align:center;line-height:1.2;word-break:break-all">{{ p.process_name }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
</template>

<script>
import { useWage } from '@/composables/useWage.js'

export default {
  setup() {
    return { ...useWage() }
  }
}
</script>
