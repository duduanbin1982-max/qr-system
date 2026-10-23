<template>
  <div>
    <!-- Pie Chart -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="modelGroups.length">
      <div class="card-header"><h3>🥧 型号规格分布</h3></div>
      <div class="card-body">
        <div style="height:360px"><canvas ref="pieCanvas"></canvas></div>
      </div>
    </div>

    <!-- Bar Chart: Top 15 -->
    <div class="card" style="margin-bottom:var(--space-4)" v-if="modelGroups.length">
      <div class="card-header"><h3>📊 型号排行 (Top 15)</h3></div>
      <div class="card-body">
        <div style="height:340px"><canvas ref="barCanvas"></canvas></div>
      </div>
    </div>

    <!-- Detail Table -->
    <div class="card" v-if="modelGroups.length">
      <div class="card-header"><h3>📋 型号 × 规格明细</h3></div>
      <div class="card-body" style="overflow-x:auto">
        <table class="table">
          <thead><tr>
            <th>#</th><th>型号</th><th>规格</th><th>入库数量</th><th>占比</th>
          </tr></thead>
          <tbody>
            <tr v-for="(g, i) in modelGroups" :key="g.key">
              <td style="color:var(--text-placeholder)">{{ i+1 }}</td>
              <td style="font-weight:600">{{ g.model || '-' }}</td>
              <td>{{ g.spec || '-' }}</td>
              <td style="font-weight:600">{{ g.count }}</td>
              <td>
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="flex:1;height:6px;background:var(--bg-hover);border-radius:3px;overflow:hidden">
                    <div :style="{width:g.pct+'%',height:'100%',background:'var(--primary)',borderRadius:'3px'}"></div>
                  </div>
                  <span style="font-size:var(--text-xs);color:var(--text-placeholder);white-space:nowrap">{{ g.pct }}%</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div style="margin-top:12px;font-size:var(--text-xs);color:var(--text-placeholder);text-align:right">
          共 {{ modelGroups.length }} 种型号规格 · 总计 {{ totalQty }} 件
        </div>
      </div>
    </div>

    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <p v-if="!modelGroups.length && !loading" class="empty"><span class="empty-text">暂无入库数据</span></p>
  </div>
</template>

<script>
import { useReportModels } from '@/composables/reports/useReportModels.js'

export default {
  setup() {
    return useReportModels()
  }
}
</script>
