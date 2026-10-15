<!-- InspectionList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🔍</span><div><div class="s-val">{{ stats.total }}</div><div class="s-label">抽检总数</div></div></div>
      <div class="summary-item"><span class="s-icon">📊</span><div><div class="s-val text-primary">{{ stats.avg_score || 0 }}</div><div class="s-label">平均分</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ stats.pass }}</div><div class="s-label">合格</div></div></div>
      <div class="summary-item"><span class="s-icon">🔄</span><div><div class="s-val text-warning">{{ stats.rework }}</div><div class="s-label">返修</div></div></div>
      <div class="summary-item"><span class="s-icon">❌</span><div><div class="s-val text-danger">{{ stats.scrap }}</div><div class="s-label">报废</div></div></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>🔍 抽检记录</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <select class="form-input" v-model="filterResult" @change="load" style="width:100px">
            <option value="">全部</option>
            <option value="pass">合格</option>
            <option value="rework">返修</option>
            <option value="scrap">报废</option>
          </select>
          <input class="form-input" v-model="keyword" placeholder="搜索订单/产品..." @keyup.enter="load" style="width:160px">
          <button class="btn btn-default btn-sm" @click="load">搜索</button>
          <button class="btn btn-default btn-sm" @click="exportExcel">📥导出</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="items.length" class="data-table" style="min-width:800px">
            <thead><tr>
              <th>订单号</th><th>产品编码</th><th>工序</th><th>判定</th><th>评分</th><th>缺陷等级</th><th>建议</th><th>返修工序</th><th>质检员</th><th>备注</th><th>时间</th><th style="width:60px;text-align:center">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in items" :key="r.id">
                <td><code>{{ r.order_no || '-' }}</code></td>
                <td><code style="font-size:var(--text-xs-alt)">{{ r.product_code || '-' }}</code></td>
                <td>{{ r.process_name }}</td>
                <td><span class="badge" :class="resultClass(r.result)">{{ resultLabel(r.result) }}</span></td>
                <td><b :style="{color:(r.score_total||0) >= 85 ? 'var(--success)' : (r.score_total||0) >= 60 ? 'var(--warning)' : 'var(--danger)'}">{{ r.score_total || '-' }}</b></td>
                <td>{{ defectLevelLabel(r.defect_level) }}</td>
                <td><span v-if="r.suggested_result" class="badge" :class="resultClass(r.suggested_result)">{{ resultLabel(r.suggested_result) }}</span><span v-else>-</span></td>
                <td>{{ r.rework_process || '-' }}</td>
                <td>{{ r.inspector_name || '-' }}</td>
                <td style="font-size:var(--text-xs);max-width:120px;overflow:hidden;text-overflow:ellipsis">{{ r.remark || '-' }}</td>
                <td style="font-size:var(--text-xs);white-space:nowrap">{{ r.created_at }}</td><td style="text-align:center"><span class="o-abtn o-del" @click="del(r)" title="删除">🗑️</span></td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-icon">🔍</div><div class="empty-text">暂无抽检记录</div></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { useInspectionList } from '@/composables/quality/useInspectionList.js'

export default {
  setup() {
    return useInspectionList()
  }
}
</script>
