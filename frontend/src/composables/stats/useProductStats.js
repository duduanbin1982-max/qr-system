import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, createExporter, buildParams } from '@/composables/reports/reportSupport.js'

export function useProductStats(props) {
  const productList = ref([]); const productSummary = ref({})
  const loading = ref(false); const updateTime = ref('')

  function specSummary(p) {
    const parts = []
    if (p.upper_opening) parts.push('上口' + p.upper_opening)
    if (p.lower_opening) parts.push('下口' + p.lower_opening)
    if (p.plate_thickness) parts.push('板厚' + p.plate_thickness)
    if (p.weight) parts.push(p.weight + 'kg')
    return parts.join(' | ') || '-'
  }

  function formatMoney(v) {
    return v ? v.toLocaleString('zh-CN') : '0'
  }

  const load = createLoader(loading, updateTime, async () => {
    const d = await api.domains.stats.productStats(buildParams(props.start, props.end, props.productCode))
    productList.value = d.by_product || []; productSummary.value = d.summary || {}
  })
  const exportProduct = createExporter(productList, ['产品名称','产品编码','型号','规格','分类','规格参数','订单数量','产量','报废','返工','产值','涉及订单数'], p => [p.product_name,p.product_code||'',p.model||'',p.spec||'',p.category||'',specSummary(p),p.order_qty||0,p.output,p.scrap,p.rework,(p.output||0)*(p.price||0),p.order_count], '产品统计')
  watch(() => [props.start, props.end, props.productCode], load)
  onMounted(load)
  return { productList, productSummary, specSummary, formatMoney, exportProduct }
}
