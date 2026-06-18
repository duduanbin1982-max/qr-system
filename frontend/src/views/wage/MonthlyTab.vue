<!-- MonthlyTab.vue -->
<template>
<div v-if="activeTab==='monthly'">
      <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
        <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) 20px">
          <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);margin:0">📊 月度工资汇总</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto">
            <input v-model="monthlyMonth" type="month" class="form-input" style="width:160px;font-size:var(--text-sm);padding:var(--space-1) 8px" @change="loadMonthly">
            <button class="btn-default btn-sm" @click="loadMonthly">查询</button>
            <button class="btn-primary btn-sm" @click="exportMonthlyCSV" style="background:var(--success);border-color:var(--success)">📥 导出</button>
          </div>
        </div>
        <div v-if="monthlyLoading" style="text-align:center;padding:60px">⏳ 加载中...</div>
        <div v-else-if="monthlyData.summary.length" style="padding:0 20px 20px">
          <div class="summary-bar" style="margin-top:12px">
            <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val text-primary">{{ monthlyData.summary.length }}</div><div class="s-label">员工数</div></div></div>
            <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val text-success">{{ monthlyData.grand_total_quantity }}</div><div class="s-label">总件数</div></div></div>
            <div class="summary-item"><span class="s-icon">💰</span><div><div class="s-val" style="color:var(--warning)">¥{{ fmtMoney(monthlyData.grand_total_wage) }}</div><div class="s-label">总工资</div></div></div>
          </div>
          <table style="width:100%;border-collapse:collapse;margin-top:12px">
            <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">排名</th>
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">姓名</th>
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">工号</th>
              <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500">总件数</th>
              <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500">总工资</th>
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">占比</th>
            </tr></thead>
            <tbody>
              <tr v-for="(s,i) in monthlyData.summary" :key="s.user_id||i" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm)">
                <td style="padding:var(--space-3) 12px;color:var(--text-placeholder)">{{ i+1 }}</td>
                <td style="padding:var(--space-3) 12px;font-weight:600">{{ s.employee_name }}</td>
                <td style="padding:var(--space-3) 12px;color:var(--text-placeholder)">{{ s.employee_no || '-' }}</td>
                <td style="padding:var(--space-3) 12px;text-align:center">{{ s.total_quantity }}</td>
                <td style="padding:var(--space-3) 12px;text-align:right;font-weight:600;color:var(--warning-dark)">¥{{ fmtMoney(s.total_wage) }}</td>
                <td style="padding:var(--space-3) 12px">
                  <div style="display:flex;align-items:center;gap:8px">
                    <div style="flex:1;height:6px;background:var(--bg-secondary);border-radius:3px;overflow:hidden">
                      <div :style="{width:monthlyPercent(s.total_wage)+'%',height:'100%',background:'linear-gradient(90deg,var(--warning),var(--warning-dark))',borderRadius:'3px'}"></div>
                    </div>
                    <span style="font-size:var(--text-xs);color:var(--text-placeholder);white-space:nowrap">{{ monthlyPercent(s.total_wage) }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="monthlyTotalPages > 1" style="display:flex;align-items:center;justify-content:center;gap:var(--space-3);padding:var(--space-3) 20px;border-top:1px solid var(--border-light)">
            <button class="btn-default btn-sm" @click="monthlyPrevPage" :disabled="monthlyPage<=1">◀ 上一页</button>
            <span style="font-size:var(--text-xs);color:var(--text-placeholder)">第 {{ monthlyPage }} / {{ monthlyTotalPages }} 页 · 共 {{ monthlyTotal }} 人</span>
            <button class="btn-default btn-sm" @click="monthlyNextPage" :disabled="monthlyPage>=monthlyTotalPages">下一页 ▶</button>
          </div>
        </div>
        <div v-else style="text-align:center;padding:60px;color:var(--text-placeholder)"><p style="font-size:48px;margin:0">📊</p><p style="margin-top:12px">暂无月度汇总数据</p></div>
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
