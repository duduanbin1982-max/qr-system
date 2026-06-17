<!-- AdjustmentTab.vue -->
<template>
<div v-if="activeTab==='adjustment'">
      <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
        <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) 20px">
          <h3 style="font-size:var(--text-lg);font-weight:700;margin:0">💵 工资调整</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto">
            <input v-model="adjMonth" type="month" class="form-input" style="width:160px;font-size:var(--text-sm)" @change="loadAdjustments">
            <button class="btn-default btn-sm" @click="loadAdjustments">查询</button>
            <button class="btn-primary btn-sm" @click="showAdjForm=true" style="background:var(--success);border-color:var(--success)">+ 新增调整</button>
          </div>
        </div>
        <div v-if="showAdjForm" style="padding:16px 20px;background:var(--bg-secondary);border-bottom:1px solid var(--border-light);display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:var(--text-xs);color:var(--text-placeholder)">员工</label>
            <select v-model="adjForm.user_id" class="form-input" style="width:140px;font-size:var(--text-sm);padding:4px 8px">
              <option v-for="e in employeeList" :key="e.id" :value="e.id">{{ e.name }}</option>
            </select>
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:var(--text-xs);color:var(--text-placeholder)">类型</label>
            <select v-model="adjForm.type" class="form-input" style="width:120px;font-size:var(--text-sm);padding:4px 8px">
              <option value="bonus">🎁 奖金</option>
              <option value="deduction">➖ 扣款</option>
              <option value="allowance">📋 补贴</option>
            </select>
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:var(--text-xs);color:var(--text-placeholder)">金额 (元)</label>
            <input v-model.number="adjForm.amount" type="number" step="0.01" min="0" class="form-input" style="width:120px;font-size:var(--text-sm);padding:4px 8px">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:var(--text-xs);color:var(--text-placeholder)">原因</label>
            <input v-model="adjForm.reason" class="form-input" style="width:180px;font-size:var(--text-sm);padding:4px 8px" placeholder="如：全勤奖">
          </div>
          <button class="btn-primary btn-sm" @click="saveAdjustment" style="height:32px">保存</button>
          <button class="btn-default btn-sm" @click="showAdjForm=false" style="height:32px">取消</button>
        </div>
        <div v-if="adjLoading" style="text-align:center;padding:60px">⏳ 加载中...</div>
        <div v-else-if="!adjustments.length" style="text-align:center;padding:60px;color:var(--text-placeholder)">暂无调整记录</div>
        <div v-else style="padding:0 20px 20px">
          <table style="width:100%;border-collapse:collapse;margin-top:12px">
            <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">员工</th>
              <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:80px">类型</th>
              <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500;width:100px">金额</th>
              <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">原因</th>
              <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:90px">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="a in adjustments" :key="a.id" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm)">
                <td style="padding:var(--space-3) 12px;font-weight:600">{{ a.employee_name }}</td>
                <td style="padding:var(--space-3) 12px;text-align:center">
                  <span :style="{padding:'2px 8px',borderRadius:'10px',fontSize:'11px',background:a.type==='bonus'?'var(--success-light)':a.type==='deduction'?'var(--danger-light)':'var(--primary-light)',color:a.type==='bonus'?'var(--success)':a.type==='deduction'?'var(--danger)':'var(--primary)'}">{{ a.type==='bonus'?'奖金':a.type==='deduction'?'扣款':'补贴' }}</span>
                </td>
                <td style="padding:var(--space-3) 12px;text-align:right;font-weight:600" :style="{color:a.type==='deduction'?'var(--danger)':'var(--success)'}">{{ a.type==='deduction'?'-':'' }}¥{{ fmtMoney(a.amount) }}</td>
                <td style="padding:var(--space-3) 12px;color:var(--text-secondary)">{{ a.reason || '-' }}</td>
                <td style="padding:var(--space-3) 12px;text-align:center">
                  <button class="btn-default" style="font-size:var(--text-xs);padding:2px 8px;color:var(--danger)" @click="deleteAdjustment(a.id)">🗑️</button>
                </td>
              </tr>
            </tbody>
          </table>
          <div style="margin-top:12px;padding-top:12px;border-top:2px solid var(--border-light);display:flex;justify-content:flex-end;gap:24px;font-weight:600;font-size:var(--text-sm)">
            <span>💰 合计调整: <span :style="{color:adjNet>=0?'var(--success)':'var(--danger)'}">{{ adjNet>=0?'+':'' }}¥{{ fmtMoney(Math.abs(adjNet)) }}</span></span>
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
