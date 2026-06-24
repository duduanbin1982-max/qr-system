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
import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, buildParams, exportCSV } from "./shared.js"
export default {
  props: { start: String, end: String },
  setup(props) {
    const processList = ref([]); const productList = ref([])
    const loading = ref(false); const updateTime = ref('')
    const load = createLoader(loading, updateTime, async () => {
      const d = await api.productProcessStats(buildParams(props.start, props.end, ''))
      const procNames = d.processes || []
      processList.value = procNames.map((name, i) => ({ id: i, name }))
      productList.value = (d.products || []).map(p => ({
        product_code: p.product_code,
        data: procNames.map(name => p.data ? (p.data[name] || 0) : 0),
        total: p.data ? Object.values(p.data).reduce((s, v) => s + (v || 0), 0) : 0
      }))
    })
    const exportData = () => {
      const h = ['序号','产品编码']
      processList.value.forEach(pr => h.push(pr.name))
      h.push('合计')
      const rows = productList.value.map((p,i) => {
        const r = [i+1, p.product_code]
        p.data.forEach(v => r.push(v||0))
        r.push(p.total)
        return r
      })
      const dt = props.start ? props.start + '_' + (props.end||'') : new Date().toISOString().slice(0,10); exportCSV([h, ...rows], '工序统计_'+dt)
    }
    watch(() => [props.start, props.end], load)
    onMounted(load)
    return { processList, productList, exportData }
  }
}
</script>