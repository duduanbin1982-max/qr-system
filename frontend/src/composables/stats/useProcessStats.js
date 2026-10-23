import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, buildParams, exportCSV } from "@/composables/reports/reportSupport.js"

export function useProcessStats(props) {
  const processList = ref([]); const productList = ref([])
  const loading = ref(false); const updateTime = ref('')
  const load = createLoader(loading, updateTime, async () => {
    const d = await api.domains.stats.productProcessStats(buildParams(props.start, props.end, ''))
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
