<!-- CompareTab.vue -->
<template>
<div v-if="activeTab==='compare'">
      <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
        <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) 20px">
          <h3 style="font-size:var(--text-lg);font-weight:700;margin:0">📈 工资对比</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto">
            <input v-model="compareMonthA" type="month" class="form-input" style="width:150px;font-size:var(--text-sm)">
            <span style="color:var(--text-placeholder);font-weight:700">vs</span>
            <input v-model="compareMonthB" type="month" class="form-input" style="width:150px;font-size:var(--text-sm)">
            <button class="btn-primary btn-sm" @click="loadCompare">对比</button>
          </div>
        </div>
        <div v-if="compareLoading" style="text-align:center;padding:60px">⏳ 加载中...</div>
        <div v-else-if="compareData.length" style="padding:0 20px 20px">
          <table style="width:100%;border-collapse:collapse">
            <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">姓名</th>
              <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500">{{ compareMonthA }} 工资</th>
              <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500">{{ compareMonthB }} 工资</th>
              <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500">变化</th>
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">趋势</th>
            </tr></thead>
            <tbody>
              <tr v-for="c in compareData" :key="c.employee_name" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm)">
                <td style="padding:var(--space-3) 12px;font-weight:600">{{ c.employee_name }}</td>
                <td style="padding:var(--space-3) 12px;text-align:right">¥{{ fmtMoney(c.wageA) }}</td>
                <td style="padding:var(--space-3) 12px;text-align:right">¥{{ fmtMoney(c.wageB) }}</td>
                <td style="padding:var(--space-3) 12px;text-align:right;font-weight:600" :style="{color:c.change>0?'var(--success)':c.change<0?'var(--danger)':'var(--text-placeholder)'}">
                  {{ c.change>0?'+':'' }}{{ fmtMoney(c.change) }}
                </td>
                <td style="padding:var(--space-3) 12px">
                  <span v-if="c.change>0" style="color:var(--success)">📈 ↑{{ c.changePct }}%</span>
                  <span v-else-if="c.change<0" style="color:var(--danger)">📉 ↓{{ Math.abs(c.changePct) }}%</span>
                  <span v-else style="color:var(--text-placeholder)">— 持平</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else style="text-align:center;padding:60px;color:var(--text-placeholder)">请选择两个月进行对比</div>
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
