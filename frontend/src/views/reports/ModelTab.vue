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
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  setup() {
    const loading = ref(true)
    const inventory = ref([])
    const pieCanvas = ref(null)
    const barCanvas = ref(null)
    let pieChart = null
    let barChart = null

    const modelGroups = computed(() => {
      const map = {}
      inventory.value.forEach(item => {
        const model = (item.product_model || '未知').trim()
        const spec = (item.specification || '-').trim()
        const key = model + '|' + spec
        if (!map[key]) map[key] = { model, spec, count: 0 }
        map[key].count += Number(item.quantity || 0)
      })
      const groups = Object.values(map).sort((a, b) => b.count - a.count)
      const total = groups.reduce((s, g) => s + g.count, 0)
      groups.forEach(g => {
        g.key = g.model + '|' + g.spec
        g.pct = total > 0 ? parseFloat((g.count / total * 100).toFixed(1)) : 0
      })
      return groups
    })

    const totalQty = computed(() => modelGroups.value.reduce((s, g) => s + g.count, 0))

    async function load() {
      loading.value = true
      try {
        const d = await api.get('/api/inventory')
        inventory.value = d.items || []
        await nextTick()
        renderPie()
        renderBar()
      } catch (e) {
        showToast('加载型号分布失败', 'error')
      } finally {
        loading.value = false
      }
    }

    function renderPie() {
      if (pieChart) { pieChart.destroy(); pieChart = null }
      if (!pieCanvas.value || !modelGroups.value.length || typeof Chart === 'undefined') return
      const top15 = modelGroups.value.slice(0, 15)
      const otherCount = modelGroups.value.slice(15).reduce((s, g) => s + g.count, 0)
      const labels = top15.map(g => g.model + ' ' + g.spec)
      const data = top15.map(g => g.count)
      if (otherCount > 0) { labels.push('其他'); data.push(otherCount) }

      pieChart = new Chart(pieCanvas.value.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels,
          datasets: [{
            data,
            backgroundColor: ['#2563EB','#22C55E','#F59E0B','#EF4444','#8B5CF6','#06B6D4','#F97316','#84CC16','#EC4899','#6366F1','#14B8A6','#E11D48','#9333EA','#0EA5E9','#D946EF','#9CA3AF']
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'right', labels: { font: { size: 11 }, padding: 8 } },
            tooltip: { callbacks: { label: ctx => ctx.label + ': ' + ctx.raw + ' 件 (' + (ctx.raw/totalQty.value*100).toFixed(1) + '%)' } }
          }
        }
      })
    }

    function renderBar() {
      if (barChart) { barChart.destroy(); barChart = null }
      if (!barCanvas.value || !modelGroups.value.length || typeof Chart === 'undefined') return
      const top15 = modelGroups.value.slice(0, 15)

      barChart = new Chart(barCanvas.value.getContext('2d'), {
        type: 'bar',
        data: {
          labels: top15.map(g => g.model + '\n' + g.spec),
          datasets: [{
            label: '入库数量',
            data: top15.map(g => g.count),
            backgroundColor: top15.map((_, i) => ['#2563EB','#22C55E','#F59E0B','#EF4444','#8B5CF6','#06B6D4','#F97316','#84CC16','#EC4899','#6366F1','#14B8A6','#E11D48','#9333EA','#0EA5E9','#D946EF'][i]),
            borderRadius: 4
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: '件数' } },
            x: { ticks: { font: { size: 10 } } }
          }
        }
      })
    }

    function destroyCharts() {
      if (pieChart) { pieChart.destroy(); pieChart = null }
      if (barChart) { barChart.destroy(); barChart = null }
    }

    onMounted(load)
    onBeforeUnmount(destroyCharts)

    return { loading, modelGroups, totalQty, pieCanvas, barCanvas }
  }
}
</script>
