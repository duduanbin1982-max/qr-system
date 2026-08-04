<!-- wage/PieceworkTab.vue — 计件工资明细 -->
<template>
<div>
  <div class="summary-bar">
    <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val text-primary">{{ filteredWages.length }}</div><div class="s-label">员工数</div></div></div>
    <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val text-success">{{ grandQty() }}</div><div class="s-label">总件数</div></div></div>
    <div class="summary-item"><span class="s-icon">💰</span><div><div class="s-val" style="color:var(--warning)">¥{{ fmtMoney(grandTotal()) }}</div><div class="s-label">总工资</div></div></div>
  </div>

  <div style="padding:8px 12px;background:var(--warning-lighter);border-left:3px solid var(--warning);margin-bottom:12px;font-size:var(--text-xs);color:var(--text-secondary)">
    实时预估仅用于核对报工和当前工价，不作为正式工资凭证。正式结算以已确认的版本化工资台账为准。
  </div>

  <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
    <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap;padding:var(--space-3) 20px">
      <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:var(--space-2);margin:0">
        <span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--warning),var(--warning-dark));border-radius:var(--radius-md);font-size:var(--text-lg);color:white">💰</span>
        实时工资预估
      </h3>
      <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:4px;font-size:var(--text-xs);cursor:pointer"><input type="checkbox" v-model="includeRework" @change="load"> 含返工</label>
        <label style="display:flex;align-items:center;gap:4px;font-size:var(--text-xs);cursor:pointer"><input type="checkbox" v-model="hideZero" @change="load"> 隐藏未报工</label>
        <input v-model="dateFrom" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="load">
        <span style="color:var(--text-placeholder);font-size:var(--text-xs)">至</span>
        <input v-model="dateTo" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="load">
        <button class="btn-default btn-sm" @click="load()" style="margin-left:4px">查询</button>
        <button class="btn-primary btn-sm" @click="exportCSV" style="margin-left:4px;background:var(--success);border-color:var(--success)">📥 导出CSV</button>
      </div>
    </div>

    <div v-if="loading" style="text-align:center;padding:60px;color:var(--text-placeholder)">⏳ 加载中...</div>
    <div v-else-if="!filteredWages.length" style="text-align:center;padding:60px;color:var(--text-placeholder)"><p style="font-size:48px;margin:0">💰</p><p style="margin-top:12px">暂无工资数据</p></div>
    <div v-else style="padding:0 20px 20px">
      <table style="width:100%;border-collapse:collapse">
        <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
          <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:30px"></th>
          <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:90px">姓名</th>
          <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">岗位</th>
          <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">工号</th>
          <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:80px">总件数</th>
          <th style="padding:var(--space-3) 12px;text-align:right;font-weight:500;width:100px">总工资</th>
          <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">明细</th>
        </tr></thead>
        <tbody>
          <template v-for="(w, wi) in filteredWages" :key="w.employee_id">
            <tr @click="toggle(w.employee_id)" style="cursor:pointer;border-bottom:1px solid var(--bg-hover);transition:background .15s;font-size:var(--text-sm)" :style="{background:expandedId===w.employee_id?'var(--bg-hover)':'transparent'}">
              <td style="padding:var(--space-3) 12px;color:var(--text-placeholder)">{{ wi+1 }}</td>
              <td style="padding:var(--space-3) 12px;font-weight:600">{{ w.employee_name }}</td>
              <td style="padding:var(--space-3) 12px;color:var(--text-placeholder)">{{ w.position_name || '-' }}</td>
              <td style="padding:var(--space-3) 12px;color:var(--text-placeholder)">{{ w.employee_no || '-' }}</td>
              <td style="padding:var(--space-3) 12px;text-align:center;font-weight:500">{{ w.total_quantity }}</td>
              <td style="padding:var(--space-3) 12px;text-align:right;font-weight:600;color:var(--warning-dark)">¥{{ fmtMoney(w.total_wage) }}</td>
              <td style="padding:var(--space-3) 12px;color:var(--text-placeholder)">{{ (w.details||[]).length }} 条</td>
            </tr>
            <tr v-if="expandedId===w.employee_id">
              <td colspan="7" style="padding:0;background:var(--bg-secondary)">
                <table style="width:100%;border-collapse:collapse;margin:var(--space-2) 0">
                  <thead><tr style="background:var(--bg-tertiary);font-size:var(--text-xs);color:var(--text-placeholder)">
                    <th style="padding:var(--space-2) 8px;text-align:left;font-weight:400;white-space:nowrap">日期</th>
                    <th style="padding:var(--space-2) 8px;text-align:left;font-weight:400;white-space:nowrap">订单号</th>
                    <th style="padding:var(--space-2) 8px;text-align:left;font-weight:400;white-space:nowrap">产品</th>
                    <th style="padding:var(--space-2) 8px;text-align:left;font-weight:400;white-space:nowrap">工序</th>
                    <th style="padding:var(--space-2) 8px;text-align:center;font-weight:400;white-space:nowrap">数量</th>
                    <th style="padding:var(--space-2) 8px;text-align:right;font-weight:400;white-space:nowrap">单价</th>
                    <th style="padding:var(--space-2) 8px;text-align:right;font-weight:400;white-space:nowrap">工资</th>
                  </tr></thead>
                  <tbody>
                    <tr v-for="(d, i) in w.details" :key="i" style="border-bottom:1px solid var(--bg-hover)">
                      <td style="padding:var(--space-2) 8px;color:var(--text-placeholder);white-space:nowrap">{{ fmtDate(d.date) }}</td>
                      <td style="padding:var(--space-2) 8px;font-weight:500;color:var(--primary);white-space:nowrap">{{ d.order_no }}</td>
                      <td style="padding:var(--space-2) 8px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px">{{ d.product_name }}<span v-if="d.product_code" style="color:var(--text-placeholder);font-size:var(--text-xs-alt);margin-left:4px">({{ d.product_code }})</span></td>
                      <td style="padding:var(--space-2) 8px;color:var(--primary-accent);white-space:nowrap">{{ d.process_name }}</td>
                      <td style="padding:var(--space-2) 8px;text-align:center;font-weight:500;white-space:nowrap">{{ d.quantity }}</td>
                      <td style="padding:var(--space-2) 12px;text-align:right;color:var(--text-placeholder)">¥{{ fmtMoney(d.unit_price) }}</td>
                      <td style="padding:var(--space-2) 12px;text-align:right;font-weight:600;color:var(--success)">¥{{ fmtMoney(d.wage) }}</td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <div v-if="totalPages > 1" style="display:flex;align-items:center;justify-content:center;gap:var(--space-3);padding:var(--space-3) 20px;border-top:1px solid var(--border-light)">
      <button class="btn-default btn-sm" @click="prevPage" :disabled="page<=1">◀ 上一页</button>
      <span style="font-size:var(--text-xs);color:var(--text-placeholder)">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 人</span>
      <button class="btn-default btn-sm" @click="nextPage" :disabled="page>=totalPages">下一页 ▶</button>
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
