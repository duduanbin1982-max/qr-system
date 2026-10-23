<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">共 {{ productSummary.product_count || 0 }} 产品，{{ productSummary.order_count || 0 }} 订单</span>
        <button class="btn btn-outline btn-sm" @click="exportProduct" :disabled="!productList.length">📥 CSV</button>
      </div>
    </div>
    <div class="card"><div class="card-header"><h3>🏷️ 产品产量排名</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="productList.length" class="data-table">
        <thead><tr><th>#</th><th>产品名称</th><th>编码</th><th>型号</th><th>规格</th><th>分类</th><th>规格参数</th><th style="text-align:center">订单数量</th><th style="text-align:center">产量</th><th style="text-align:center">报废</th><th style="text-align:center">返工</th><th style="text-align:right">产值</th><th style="text-align:center">涉及订单</th></tr></thead>
        <tbody><tr v-for="(p,i) in productList" :key="p.id">
          <td>{{ i+1 }}</td><td style="font-weight:500">{{ p.product_name }}</td><td>{{ p.product_code }}</td>
          <td>{{ p.model }}</td><td>{{ p.spec }}</td><td><span class="badge badge-info">{{ p.category }}</span></td>
          <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ specSummary(p) }}</td>
          <td style="text-align:center">{{ p.order_qty || 0 }}</td>
          <td style="text-align:center;color:var(--success);font-weight:600">{{ p.output }}</td>
          <td style="text-align:center;color:var(--danger)">{{ p.scrap }}</td>
          <td style="text-align:center;color:var(--warning)">{{ p.rework }}</td>
          <td style="text-align:right;color:var(--primary);font-weight:600">{{ formatMoney((p.output||0)*(p.price||0)) }}</td>
          <td style="text-align:center">{{ p.order_count }}</td>
        </tr></tbody>
      </table><p v-else class="empty"><span class="empty-text">无产品数据</span></p></div></div>
    </div>
  </div>
</template>
<script>
import { useProductStats } from '@/composables/stats/useProductStats.js'

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    return useProductStats(props)
  }
}
</script>
