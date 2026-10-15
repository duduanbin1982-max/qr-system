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
import { useReportQuality } from '@/composables/reports/useReportQuality.js'

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    return useReportQuality(props)
  }
}
</script>
<style scoped>
.loading-container { padding: 20px; }
.skeleton { background: linear-gradient(90deg, var(--bg-secondary) 25%, var(--bg-tertiary) 50%, var(--bg-secondary) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 8px; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
</style>
