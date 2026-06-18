<!-- PredictTab.vue -->
<template>
<div v-if="activeTab==='predict'">
      <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
        <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) 20px">
          <h3 style="font-size:var(--text-lg);font-weight:700;margin:0">🔮 工资预测</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto">
            <select v-model="predMonths" class="form-input" style="width:120px;font-size:var(--text-sm)" >
              <option :value="3">近3月</option>
              <option :value="6">近6月</option>
              <option :value="12">近12月</option>
            </select>
            <button class="btn-primary btn-sm" @click="loadPrediction">刷新</button>
          </div>
        </div>
        <div v-if="predLoading" style="text-align:center;padding:60px">⏳ 加载中...</div>
        <div v-else-if="!predData.predicted_wage" style="text-align:center;padding:60px;color:var(--text-placeholder)">
          <p style="font-size:48px;margin:0">🔮</p>
          <p style="margin-top:12px">需要至少2个月的数据才能预测，请先保存多月快照</p>
        </div>
        <div v-else style="padding:20px">
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px">
            <div class="card" style="padding:16px;text-align:center;background:linear-gradient(135deg,var(--warning-light),var(--bg))">
              <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-bottom:4px">预测下月工资</div>
              <div style="font-size:28px;font-weight:700;color:var(--warning)">¥{{ fmtMoney(predData.predicted_wage) }}</div>
            </div>
            <div class="card" style="padding:16px;text-align:center;background:linear-gradient(135deg,var(--success-light),var(--bg))">
              <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-bottom:4px">月均工资</div>
              <div style="font-size:28px;font-weight:700;color:var(--success)">¥{{ fmtMoney(predData.avg_wage) }}</div>
            </div>
            <div class="card" style="padding:16px;text-align:center;background:linear-gradient(135deg,var(--primary-light),var(--bg))">
              <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-bottom:4px">趋势</div>
              <div style="font-size:24px;font-weight:700;color:var(--primary)">
                <span v-if="predData.trend==='up'">📈 上升</span>
                <span v-else-if="predData.trend==='down'">📉 下降</span>
                <span v-else>➡️ 稳定</span>
              </div>
            </div>
          </div>
          <div style="padding:12px;background:var(--bg-secondary);border-radius:var(--radius-md);text-align:center">
            <span style="font-size:var(--text-xs);color:var(--text-placeholder)">
              置信度: <b :style="{color:predData.confidence>60?'var(--success)':'var(--warning)'}">{{ predData.confidence }}%</b>
              · 基于 {{ predData.months_data }} 个月数据
            </span>
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
