<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header"><h3>🥧 订单状态分布</h3></div>
      <div class="card-body">
        <div style="height:340px"><canvas ref="pieCanvas"></canvas></div>
        <div v-if="completionRate !== null" style="text-align:center;margin-top:var(--space-3);font-size:var(--text-sm);color:var(--text-placeholder)">
          整体完成率：<strong style="color:var(--primary)">{{ completionRate }}%</strong>（已完成 {{ totalDone }} / 总计 {{ totalQty }} 件）
        </div>
      </div>
    </div>
    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">加载中...</div>
    <p v-if="!byStatus.length && !loading" class="empty"><span class="empty-text">暂无订单数据</span></p>
    <div class="card" v-if="monthly.length">
      <div class="card-header"><h3>📊 月度订单趋势</h3></div>
      <div class="card-body"><div style="height:320px"><canvas ref="barCanvas"></canvas></div></div>
    </div>
  </div>
</template>
<script>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const STATUS_MAP = { pending:'待生产', producing:'生产中', completed:'已完成', paused:'已暂停', cancelled:'已取消' }
const STATUS_COLORS = { pending:'#94A3B8', producing:'#2563EB', completed:'#22C55E', paused:'#F59E0B', cancelled:'#EF4444' }

export default {
  setup() {
    const byStatus = ref([]); const monthly = ref([])
    const loading = ref(true)
    const totalQty = ref(0); const totalDone = ref(0); const completionRate = ref(null)
    const pieCanvas = ref(null); const barCanvas = ref(null)
    let pieChart = null; let barChart = null

    async function load() {
      try {
        const d = await api.orderAnalysis()
        byStatus.value = d.status_distribution || []
        monthly.value = d.monthly_trend || []
        let qty = 0, done = 0
        for (const s of byStatus.value) { qty += (s.qty || 0); done += (s.done || 0) }
        totalQty.value = qty; totalDone.value = done
        completionRate.value = qty > 0 ? +(done / qty * 100).toFixed(1) : null
        await nextTick(); renderPie(); renderBar()
      } catch(e) {
        showToast('加载订单分析失败', 'error')
      } finally { loading.value = false }
    }

    function renderPie() {
      if (pieChart) pieChart.destroy()
      if (!pieCanvas.value || !byStatus.value.length) return
      pieChart = new Chart(pieCanvas.value.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels: byStatus.value.map(s=>STATUS_MAP[s.status]||s.status),
          datasets: [{
            data: byStatus.value.map(s=>s.qty||0), borderWidth: 0,
            backgroundColor: byStatus.value.map(s=>STATUS_COLORS[s.status]||'#94A3B8')
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position:'bottom' }, tooltip: { callbacks: { label: ctx => ctx.label+': '+ctx.raw+' 件' } } }
        }
      })
    }

    function renderBar() {
      if (barChart) barChart.destroy()
      if (!barCanvas.value || !monthly.value.length) return
      barChart = new Chart(barCanvas.value.getContext('2d'), {
        type: 'bar',
        data: {
          labels: monthly.value.map(m=>m.month),
          datasets: [
            { label: '订单数', data: monthly.value.map(m=>m.count), backgroundColor: '#2563EB', borderRadius: 6 },
            { label: '已完成', data: monthly.value.map(m=>m.total_done||0), backgroundColor: '#22C55E', borderRadius: 6 }
          ]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position:'top' } }, scales: { y: { beginAtZero: true, ticks:{precision:0} } } }
      })
    }

    onMounted(load)
    onUnmounted(() => { if (pieChart) pieChart.destroy(); if (barChart) barChart.destroy() })

    return { byStatus, monthly, loading, totalQty, totalDone, completionRate, pieCanvas, barCanvas }
  }
}
</script>
