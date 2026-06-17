<!-- PositionTab.vue -->
<template>
<div v-if="activeTab==='position'">
      <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
        <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) 20px">
          <h3 style="font-size:var(--text-lg);font-weight:700;margin:0">👥 岗位工资汇总</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto">
            <input v-model="posMonth" type="month" class="form-input" style="width:160px;font-size:var(--text-sm)" @change="loadPosition">
            <button class="btn-default btn-sm" @click="loadPosition">查询</button>
          </div>
        </div>
        <div v-if="posLoading" style="text-align:center;padding:60px">⏳ 加载中...</div>
        <div v-else-if="!posData.summary || !posData.summary.length" style="text-align:center;padding:60px;color:var(--text-placeholder)">暂无岗位数据</div>
        <div v-else style="padding:0 20px 20px">
          <div class="summary-bar" style="margin-top:12px">
            <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val text-primary">{{ posData.summary.length }}</div><div class="s-label">岗位数</div></div></div>
            <div class="summary-item"><span class="s-icon">💰</span><div><div class="s-val" style="color:var(--warning)">¥{{ fmtMoney(posData.grand_total_wage) }}</div><div class="s-label">总工资</div></div></div>
          </div>
          <table style="width:100%;border-collapse:collapse;margin-top:12px">
            <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">岗位</th>
              <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500">人数</th>
              <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500">总件数</th>
              <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500">总工资</th>
              <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500">人均工资</th>
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">占比</th>
            </tr></thead>
            <tbody>
              <tr v-for="(p,i) in posData.summary" :key="p.position_name||i" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm)">
                <td style="padding:var(--space-3) 12px;font-weight:600">{{ p.position_name }}</td>
                <td style="padding:var(--space-3) 12px;text-align:center">{{ p.employee_count }}</td>
                <td style="padding:var(--space-3) 12px;text-align:center">{{ p.total_quantity }}</td>
                <td style="padding:var(--space-3) 12px;text-align:right;font-weight:600;color:var(--warning-dark)">¥{{ fmtMoney(p.total_wage) }}</td>
                <td style="padding:var(--space-3) 12px;text-align:right">¥{{ fmtMoney((p.total_wage||0)/(p.employee_count||1)) }}</td>
                <td style="padding:var(--space-3) 12px">
                  <div style="display:flex;align-items:center;gap:8px">
                    <div style="flex:1;height:6px;background:var(--bg-secondary);border-radius:3px;overflow:hidden">
                      <div :style="{width:posPercent(p.total_wage)+'%',height:'100%',background:'linear-gradient(90deg,var(--primary),var(--primary-dark))',borderRadius:'3px'}"></div>
                    </div>
                    <span style="font-size:var(--text-xs);color:var(--text-placeholder);white-space:nowrap">{{ posPercent(p.total_wage) }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
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
