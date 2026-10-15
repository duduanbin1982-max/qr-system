import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV } from '@/composables/reports/reportSupport.js'

export function useReportQuality(props) {
  let pieChart=null, hBarChart=null, trendChart=null, spcChart=null
  const loading=ref(false), chartError=ref(false)
  const byProcess=ref([]), trendLabels=ref([]), trendPassRates=ref([])
  const spcSamples=ref([]), spcUcl=ref(0), spcCl=ref(0), spcLcl=ref(0)
  const inspectorData=ref([]), supplierData=ref([]), qiByProcess=ref([])
  const pieCanvas=ref(null), hBarCanvas=ref(null), trendCanvas=ref(null), spcCanvas=ref(null)
  const hasData=computed(()=>byProcess.value.length>0||qiByProcess.value.length>0||trendLabels.value.length>0)

  function chartAvailable() {
    if (typeof Chart === 'undefined') { chartError.value=true; return false }
    return true
  }

  async function load() {
    loading.value=true; chartError.value=false
    try {
      const d = await api.domains.stats.qualityAnalysis({ start: props.start || '', end: props.end || '', product_code: props.productCode || '' })
      byProcess.value=d.by_process||[]
      qiByProcess.value=d.qi_by_process||[]
      trendLabels.value=d.trend_labels||[]
      trendPassRates.value=d.trend_pass_rates||[]
      spcSamples.value=d.spc_samples||[]
      spcUcl.value=d.spc_ucl||0; spcCl.value=d.spc_cl||0; spcLcl.value=d.spc_lcl||0
      inspectorData.value=d.inspector_data||[]
      supplierData.value=d.supplier_data||[]
      await nextTick()
      if (chartAvailable()) { renderPie(); renderHBar(); renderTrend(); renderSpc() }
    } catch(e) {
      showToast('加载品质分析失败', 'error')
    } finally { loading.value=false }
  }

  function exportData() {
    const rows=[['工序','产量','报废','返工','缺陷率','质检次数','质检合格','质检不合格']]
    byProcess.value.forEach(p=>{
      const q=qiByProcess.value.find(x=>x.name===p.name)||{}
      rows.push([p.name,p.output||0,p.scrap||0,p.rework||0,p.defect_rate+'%',q.total_inspections||0,q.pass_count||0,q.fail_count||0])
    })
    exportCSV(rows, '品质分析_'+new Date().toISOString().slice(0,10))
  }

  function renderPie() {
    if (pieChart) { pieChart.destroy(); pieChart=null }
    if (!pieCanvas.value) return
    const totalOk=byProcess.value.reduce((s,p)=>s+(p.output||0),0)
    const totalScrap=byProcess.value.reduce((s,p)=>s+(p.scrap||0),0)
    const totalRework=byProcess.value.reduce((s,p)=>s+(p.rework||0),0)
    if (totalOk+totalScrap+totalRework===0) return
    const slices=[{label:'良品',value:totalOk,color:'#22C55E'},{label:'返工',value:totalRework,color:'#F59E0B'},{label:'报废',value:totalScrap,color:'#EF4444'}].filter(s=>s.value>0)
    pieChart=new Chart(pieCanvas.value.getContext('2d'),{type:'doughnut',data:{labels:slices.map(s=>s.label),datasets:[{data:slices.map(s=>s.value),backgroundColor:slices.map(s=>s.color),borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'},tooltip:{callbacks:{label:ctx=>ctx.label+': '+ctx.raw+' 件'}}}}})
  }

  function renderHBar() {
    if (hBarChart) { hBarChart.destroy(); hBarChart=null }
    if (!hBarCanvas.value||!byProcess.value.length) return
    hBarChart=new Chart(hBarCanvas.value.getContext('2d'),{type:'bar',data:{labels:byProcess.value.map(p=>p.name),datasets:[{label:'报废数',data:byProcess.value.map(p=>p.scrap||0),backgroundColor:'#EF4444',borderRadius:4}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,ticks:{precision:0}}}}})
  }

  function renderTrend() {
    if (trendChart) { trendChart.destroy(); trendChart=null }
    if (!trendCanvas.value||!trendLabels.value.length) return
    trendChart=new Chart(trendCanvas.value.getContext('2d'),{type:'line',data:{labels:trendLabels.value,datasets:[{label:'合格率 %',data:trendPassRates.value,borderColor:'#22C55E',backgroundColor:'rgba(34,197,94,0.1)',fill:true,tension:0.3,pointRadius:3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{min:0,max:100,ticks:{callback:v=>v+'%'}}}}})
  }

  function renderSpc() {
    if (spcChart) { spcChart.destroy(); spcChart=null }
    if (!spcCanvas.value||!spcSamples.value.length) return
    spcChart=new Chart(spcCanvas.value.getContext('2d'),{type:'line',data:{labels:spcSamples.value.map((_,i)=>'样本'+(i+1)),datasets:[{label:'不合格率 %',data:spcSamples.value,borderColor:'#2563EB',pointRadius:3},{label:'UCL',data:spcSamples.value.map(()=>spcUcl.value),borderColor:'#EF4444',borderDash:[5,5],pointRadius:0,fill:false},{label:'CL',data:spcSamples.value.map(()=>spcCl.value),borderColor:'#F59E0B',borderDash:[3,3],pointRadius:0,fill:false},{label:'LCL',data:spcSamples.value.map(()=>spcLcl.value),borderColor:'#22C55E',borderDash:[5,5],pointRadius:0,fill:false}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true}}}})
  }

  function destroyAll() {
    [pieChart,hBarChart,trendChart,spcChart].forEach(c=>{if(c)c.destroy()})
    pieChart=hBarChart=trendChart=spcChart=null
  }

  watch(()=>[props.start,props.end,props.productCode], load)
  onMounted(load)
  onUnmounted(destroyAll)
  return {byProcess,hasData,loading,chartError,pieCanvas,hBarCanvas,trendCanvas,spcCanvas,trendLabels,spcSamples,spcUcl,spcCl,spcLcl,inspectorData,supplierData,qiByProcess,exportData}
}
