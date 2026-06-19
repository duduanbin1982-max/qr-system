<template>
  <div>
    <!-- Pie: Quality Ratio -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="hasData">
      <div class="card-header" style="display:flex;align-items:center;justify-content:space-between">
        <h3>🥧 良品/报废/返工比例</h3>
        <button class="btn btn-sm" @click="exportData" title="导出Excel">📥 导出</button>
      </div>
      <div class="card-body"><div style="height:340px"><canvas ref="pieCanvas"></canvas></div></div>
    </div>

    <!-- Horizontal Bar: Scrap by Process -->
    <div class="card" v-if="byProcess.length" style="margin-bottom:var(--space-4)">
      <div class="card-header"><h3>📊 各工序报废排行</h3></div>
      <div class="card-body"><div style="height:320px"><canvas ref="hBarCanvas"></canvas></div></div>
    </div>

    <!-- Trend: Pass Rate over time -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="trendLabels.length">
      <div class="card-header"><h3>📈 合格率趋势</h3></div>
      <div class="card-body"><div style="height:280px"><canvas ref="trendCanvas"></canvas></div></div>
    </div>

    <!-- SPC P-Chart -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="spcSamples.length">
      <div class="card-header" style="display:flex;align-items:center;justify-content:space-between">
        <h3>📊 SPC 不合格率控制图 (P 图)</h3>
        <span style="font-size:var(--text-xs);color:var(--text-placeholder)">UCL: {{ spcUcl }}% | CL: {{ spcCl }}% | LCL: {{ spcLcl }}%</span>
      </div>
      <div class="card-body"><div style="height:300px"><canvas ref="spcCanvas"></canvas></div></div>
    </div>

    <!-- Inspector Performance -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="inspectorData.length">
      <div class="card-header"><h3>👨‍🔧 检验员绩效</h3></div>
      <div class="card-body" style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>检验员</th><th>检验次数</th><th>检验总数</th><th>不合格数</th><th>缺陷率</th><th>涉及订单</th></tr></thead>
          <tbody>
            <tr v-for="ins in inspectorData" :key="ins.inspector_id">
              <td style="font-weight:600">{{ ins.inspector_name }}</td>
              <td>{{ ins.inspection_count }}</td>
              <td>{{ ins.total_checked }}</td>
              <td>{{ ins.total_failed }}</td>
              <td><span :style="{color:ins.overall_defect_rate>20?'var(--danger)':ins.overall_defect_rate>10?'var(--warning)':'var(--success)',fontWeight:600}">{{ ins.overall_defect_rate }}%</span></td>
              <td>{{ ins.orders_covered }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Customer Quality -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="supplierData.length">
      <div class="card-header"><h3>🏭 客户质量分析</h3></div>
      <div class="card-body" style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>客户</th><th>检验次数</th><th>检验总数</th><th>不合格数</th><th>缺陷率</th><th>合格率</th></tr></thead>
          <tbody>
            <tr v-for="sup in supplierData" :key="sup.customer_id">
              <td style="font-weight:600">{{ sup.customer_name }}</td>
              <td>{{ sup.inspection_count }}</td>
              <td>{{ sup.total_checked }}</td>
              <td>{{ sup.total_failed }}</td>
              <td><span :style="{color:sup.defect_rate>15?'var(--danger)':sup.defect_rate>8?'var(--warning)':'var(--success)',fontWeight:600}">{{ sup.defect_rate }}%</span></td>
              <td><span :style="{color:sup.pass_rate<85?'var(--danger)':sup.pass_rate<95?'var(--warning)':'var(--success)',fontWeight:600}">{{ sup.pass_rate }}%</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Defect Rate Table -->
    <div class="card" v-if="byProcess.length">
      <div class="card-header"><h3>📋 工序缺陷率明细（报工数据）</h3></div>
      <div class="card-body">
        <div style="overflow-x:auto">
          <table class="table">
            <thead><tr><th>工序</th><th>产量</th><th>报废</th><th>返工</th><th>缺陷率</th></tr></thead>
            <tbody>
              <tr v-for="p in byProcess" :key="p.id">
                <td>{{ p.name }}</td><td>{{ p.output||0 }}</td><td>{{ p.scrap||0 }}</td><td>{{ p.rework||0 }}</td>
                <td :style="{color: (p.defect_rate||0) > 5 ? 'var(--danger)' : (p.defect_rate||0) > 2 ? 'var(--warning)' : 'var(--success)'}">{{ p.defect_rate != null ? p.defect_rate+'%' : '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Quality Inspection by Process (from quality_inspections) -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="qiByProcess.length">
      <div class="card-header"><h3>📋 质检记录统计（按工序）</h3></div>
      <div class="card-body">
        <div style="overflow-x:auto">
          <table class="table">
            <thead><tr><th>工序</th><th>检验次数</th><th>合格</th><th>不合格</th><th>报废</th><th>返修</th><th>合格率</th></tr></thead>
            <tbody>
              <tr v-for="q in qiByProcess" :key="q.name">
                <td style="font-weight:600">{{ q.name }}</td>
                <td>{{ q.total_inspections }}</td>
                <td>{{ q.pass_count }}</td>
                <td>{{ q.fail_count }}</td>
                <td>{{ q.scrap_count }}</td>
                <td>{{ q.rework_count }}</td>
                <td><span :style="{color:(q.total_inspections>0?(q.pass_count/q.total_inspections*100):100)<90?'var(--danger)':(q.total_inspections>0?(q.pass_count/q.total_inspections*100):100)<98?'var(--warning)':'var(--success)',fontWeight:600}">{{ q.total_inspections > 0 ? Math.round(q.pass_count/q.total_inspections*100) : '-' }}{{ q.total_inspections > 0 ? '%' : '' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="loading-container">
      <div class="skeleton" style="height:340px;margin-bottom:16px"></div>
      <div class="skeleton" style="height:320px;margin-bottom:16px"></div>
      <div class="skeleton" style="height:280px"></div>
    </div>
    <p v-if="!hasData && !loading" class="empty"><span class="empty-text">暂无品质数据</span></p>
    <p v-if="chartError" style="text-align:center;color:var(--warning)">⚠ 图表组件加载失败，数据表格仍可正常查看</p>
  </div>
</template>
<script>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
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
        const d=await api.get('/api/reports/quality-analysis', { start:props.start||'', end:props.end||'', product_code:props.productCode||'' })
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
      const csv=rows.map(r=>r.join(',')).join('\n')
      const blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'})
      const url=URL.createObjectURL(blob)
      const a=document.createElement('a')
      a.href=url; a.download='品质分析_'+new Date().toISOString().slice(0,10)+'.csv'
      a.click(); URL.revokeObjectURL(url)
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
}
</script>
<style scoped>
.loading-container { padding: 20px; }
.skeleton { background: linear-gradient(90deg, var(--bg-secondary) 25%, var(--bg-tertiary) 50%, var(--bg-secondary) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 8px; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
</style>
