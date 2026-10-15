<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">共 {{ productList.length }} 个产品，{{ processList.length }} 道工序</span>
        <button class="btn btn-outline btn-sm" @click="exportData" :disabled="!productList.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div class="card"><div class="card-header"><h3>&#x1F3F7;&#xFE0F; 工序完工统计</h3></div>
      <div class="card-body" style="overflow-x:auto">
        <table v-if="productList.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr>
            <th style="position:sticky;left:0;background:var(--bg-table-header);z-index:1;min-width:50px;text-align:center">#</th>
            <th style="position:sticky;left:50px;background:var(--bg-table-header);z-index:1;min-width:140px">产品编码</th>
            <th v-for="pr in processList" :key="pr.id" style="min-width:52px;text-align:center;font-size:var(--text-xs)">{{ pr.name }}</th>
            <th style="background:var(--primary-lighter);min-width:52px;text-align:center">合计</th>
          </tr></thead>
          <tbody><tr v-for="(p,i) in productList" :key="p.product_code">
            <td style="position:sticky;left:0;background:var(--bg-surface);text-align:center;color:var(--text-placeholder);font-size:var(--text-xs)">{{ i+1 }}</td>
            <td style="position:sticky;left:50px;background:var(--bg-surface);font-weight:600;white-space:nowrap;font-family:monospace">{{ p.product_code }}</td>
            <td v-for="(v,j) in p.data" :key="j" style="text-align:center" :style="{color:v>0?'var(--success)':'var(--text-placeholder)',fontWeight:v>0?'600':'400'}">{{ v || '-' }}</td>
            <td style="text-align:center;background:var(--primary-lighter);font-weight:700;color:var(--primary)">{{ p.total }}</td>
          </tr></tbody>
        </table>
        <p v-else class="empty"><span class="empty-text">无统计数据</span></p>
      </div>
    </div>
  </div>
</template>
<script>
import { useProcessStats } from '@/composables/stats/useProcessStats.js'

export default {
  props: { start: String, end: String },
  setup(props) {
    return useProcessStats(props)
  }
}
</script>