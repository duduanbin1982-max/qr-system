<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">共 {{ matrixProducts.length }} 产品，{{ matrixProcesses.length }} 道工序</span>
        <button class="btn btn-outline btn-sm" @click="exportMatrix" :disabled="!matrixProducts.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div class="card"><div class="card-header"><h3>&#x1F3F7;&#xFE0F; 产品 × 工序 完工矩阵</h3></div>
      <div class="card-body" style="overflow-x:auto">
        <table v-if="matrixProducts.length" class="data-table" style="font-size:var(--text-xs)">
          <thead><tr>
            <th style="position:sticky;left:0;background:var(--bg-table-header);z-index:1">产品</th>
            <th style="position:sticky;left:120px;background:var(--bg-table-header);z-index:1">型号</th>
            <th v-for="pr in matrixProcesses" :key="pr.id" style="min-width:60px;text-align:center">{{ pr.name }}</th>
            <th style="background:var(--primary-lighter);min-width:60px;text-align:center">合计</th>
          </tr></thead>
          <tbody><tr v-for="(p,i) in matrixProducts" :key="p.product_code">
            <td style="position:sticky;left:0;background:var(--bg-surface);font-weight:500;white-space:nowrap">{{ p.product_name }}<br><small style="color:var(--text-placeholder)">{{ p.spec }}</small></td>
            <td style="position:sticky;left:120px;background:var(--bg-surface);white-space:nowrap">{{ p.model }}</td>
            <td v-for="(v,j) in p.data" :key="j" style="text-align:center" :style="{color:v>0?'var(--success)':'var(--text-placeholder)',fontWeight:v>0?'600':'400'}">{{ v || '-' }}</td>
            <td style="text-align:center;background:var(--primary-lighter);font-weight:700;color:var(--primary)">{{ p.total }}</td>
          </tr></tbody>
        </table>
        <p v-else class="empty"><span class="empty-text">无矩阵数据</span></p>
      </div>
    </div>
  </div>
</template>
<script>
import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, buildParams, exportCSV } from './shared.js'
export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    const matrixProcesses = ref([]); const matrixProducts = ref([])
    const loading = ref(false); const updateTime = ref('')
    const load = createLoader(loading, updateTime, async () => {
      const d = await api.productProcessMatrix(buildParams(props.start, props.end, props.productCode))
      matrixProcesses.value = d.processes || []; matrixProducts.value = d.products || []
    })
    const exportMatrix = () => {
      const h = ['产品','型号','规格']
      matrixProcesses.value.forEach(pr => h.push(pr.name))
      h.push('合计')
      const rows = matrixProducts.value.map(p => {
        const r = [p.product_name, p.model, p.spec]
        p.data.forEach(v => r.push(v||0))
        r.push(p.total)
        return r
      })
      exportCSV([h, ...rows], '产品工序矩阵_'+new Date().toISOString().slice(0,10))
    }
    watch(() => [props.start, props.end, props.productCode], load)
    onMounted(load)
    return { matrixProcesses, matrixProducts, exportMatrix }
  }
}
</script>
