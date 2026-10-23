import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, createExporter, buildParams } from '@/composables/reports/reportSupport.js'

export function useMaterialStats(props) {
  const materialList = ref([]); const materialSummary = ref({})
  const loading = ref(false); const updateTime = ref('')
  const load = createLoader(loading, updateTime, async () => {
    const d = await api.domains.stats.materialUsage(buildParams(props.start, props.end, props.productCode))
    materialList.value = d.by_material || []; materialSummary.value = d.summary || {}
  })
  const exportMaterial = createExporter(materialList, ['物料名称','规格','材质','单位','库存','最低库存','已消耗','涉及订单数'], m => [m.name,m.spec||'',m.material_type||'',m.unit||'',m.stock_qty,m.safe_stock,m.total_used,m.order_count], '物料消耗')
  watch(() => [props.start, props.end, props.productCode], load)
  onMounted(load)
  return { materialList, materialSummary, exportMaterial }
}
