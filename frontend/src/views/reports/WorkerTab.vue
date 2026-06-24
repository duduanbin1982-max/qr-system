<template>
  <div>
    <div class="card" v-if="workers.length">
      <div class="card-header"><h3>👷 工人效率排行</h3></div>
      <div class="card-body">
        <div style="height:480px"><canvas ref="canvas"></canvas></div>
        <div v-if="totalWorkers > 15" style="text-align:center;margin-top:var(--space-2);font-size:var(--text-xs);color:var(--text-placeholder)">
          显示前 15 名，共 {{ totalWorkers }} 名工人
        </div>
      </div>
    </div>

    <!-- Data Table -->
    <div class="card" v-if="workers.length" style="margin-top:var(--space-4)">
      <div class="card-header">
        <h3>📋 工人效率排行（前 15 名）</h3>
        <button class="btn btn-sm" @click="showTable = !showTable" style="font-size:var(--text-xs)">
          {{ showTable ? '收起' : '展开' }}
        </button>
      </div>
      <div class="card-body" v-if="showTable">
        <div style="overflow-x:auto">
          <table class="table">
            <thead>
              <tr>
                <th>排名</th><th>姓名</th><th>工号</th><th>产量</th><th>报废</th><th>返工</th>
                <th>报废率</th><th>返工率</th><th>出勤天数</th><th>日均产量</th><th>报工次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(w,i) in workers" :key="w.id" :style="{background: i<TOP_N ? 'var(--bg-highlight)' : ''}">
                <td>{{ i+1 }}</td>
                <td>{{ w.name }}</td>
                <td>{{ w.employee_no || '-' }}</td>
                <td>{{ w.output }}</td>
                <td>{{ w.scrap }}</td>
                <td>{{ w.rework }}</td>
                <td :style="{color: w.scrap_rate > 5 ? 'var(--danger)' : ''}">{{ w.scrap_rate }}%</td>
                <td :style="{color: w.rework_rate > 5 ? 'var(--warning)' : ''}">{{ w.rework_rate }}%</td>
                <td>{{ w.work_days }}</td>
                <td>{{ w.daily_avg }}</td>
                <td>{{ w.report_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <p v-else-if="!loading" class="empty"><span class="empty-text">暂无数据</span></p>
  </div>
</template>
<script>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const TOP_N = 3 // top N highlight count

export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    const workers = ref([]); const loading = ref(true); const showTable = ref(false)
    const totalWorkers = ref(0)
    const canvas = ref(null)
    let chart = null

    async function load() {
      loading.value = true
      try {
        const d = await api.workerEfficiency({ start: props.start, end: props.end, product_code: props.productCode}) 
        const all = d.workers || []
        totalWorkers.value = all.length
        workers.value = all.slice(0, 15)
        await nextTick(); renderChart()
      } catch(e) {
        showToast('加载工人效率失败', 'error')
      } finally { loading.value = false }
    }

    function renderChart() {
      if (chart) { try { chart.destroy() } catch(e) {} }
      if (!canvas.value || !workers.value.length) return
      chart = new Chart(canvas.value.getContext('2d'), {
        type: 'bar',
        data: {
          labels: workers.value.map(w => w.name),
          datasets: [{
            label: '产量', data: workers.value.map(w => w.output || 0),
            backgroundColor: workers.value.map((_,i) => i < TOP_N ? '#F59E0B' : '#2563EB'),
            borderRadius: 4
          }]
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      })
    }

    onMounted(load)
    onUnmounted(() => { if (chart) { try { chart.destroy() } catch(e) {} } })

    return { workers, loading, showTable, totalWorkers, canvas, TOP_N }
  }
}
</script>
