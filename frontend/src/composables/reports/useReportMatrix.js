import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, buildParams, exportCSV } from '@/composables/reports/reportSupport.js'

export function useReportMatrix(props) {
  const matrixProcesses = ref([]); const matrixProducts = ref([])
  const loading = ref(false); const updateTime = ref('')
  const load = createLoader(loading, updateTime, async () => {
    const d = await api.domains.stats.productProcessMatrix(buildParams(props.start, props.end, props.productCode))
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
