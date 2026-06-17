<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">共 {{ materialSummary.material_count || 0 }} 物料，累计消耗 {{ materialSummary.total_consumed || 0 }}</span>
        <button class="btn btn-outline btn-sm" @click="exportMaterial" :disabled="!materialList.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div class="card"><div class="card-header"><h3>&#x1F4E6; 物料消耗排行</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="materialList.length" class="data-table">
        <thead><tr><th>#</th><th>物料名称</th><th>规格</th><th>材质</th><th>库存</th><th>最低库存</th><th>已消耗</th><th>涉及订单</th></tr></thead>
        <tbody><tr v-for="(m,i) in materialList" :key="m.id" :style="{background: m.safe_stock>0 && m.stock_qty<=m.safe_stock ? 'var(--danger-lighter)' : ''}">
          <td>{{ i+1 }}</td><td style="font-weight:500">{{ m.name }}</td><td>{{ m.spec }}</td><td>{{ m.material_type }}</td>
          <td :style="{color: m.safe_stock>0 && m.stock_qty<=m.safe_stock ? 'var(--danger)' : ''}">{{ m.stock_qty }} {{ m.unit }}</td>
          <td>{{ m.safe_stock }} {{ m.unit }}</td>
          <td style="color:var(--primary);font-weight:600">{{ m.total_used }} {{ m.unit }}</td>
          <td>{{ m.order_count }}</td>
        </tr></tbody>
      </table><p v-else class="empty"><span class="empty-text">无物料消耗数据</span></p></div></div>
    </div>
  </div>
</template>
<script>
import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, createExporter, buildParams } from './shared.js'
export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    const materialList = ref([]); const materialSummary = ref({})
    const loading = ref(false); const updateTime = ref('')
    const load = createLoader(loading, updateTime, async () => {
      const d = await api.materialUsage(buildParams(props.start, props.end, props.productCode))
      materialList.value = d.by_material || []; materialSummary.value = d.summary || {}
    })
    const exportMaterial = createExporter(materialList, ['物料名称','规格','材质','单位','库存','最低库存','已消耗','涉及订单数'], m => [m.name,m.spec||'',m.material_type||'',m.unit||'',m.stock_qty,m.safe_stock,m.total_used,m.order_count], '物料消耗')
    watch(() => [props.start, props.end, props.productCode], load)
    onMounted(load)
    return { materialList, materialSummary, exportMaterial }
  }
}
</script>
