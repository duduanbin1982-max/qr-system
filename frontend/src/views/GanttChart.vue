<!-- GanttChart.vue -->
<template>
<div style="padding:var(--space-6);max-width:100%;overflow-x:auto">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📅</span><div><div class="s-val">{{ stats.total }}</div><div class="s-label">总订单</div></div></div>
      <div class="summary-item"><span class="s-icon">⚙️</span><div><div class="s-val text-info">{{ stats.producing }}</div><div class="s-label">生产中</div></div></div>
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val">{{ stats.pending }}</div><div class="s-label">待生产</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ stats.completed }}</div><div class="s-label">已完成</div></div></div>
    </div>

    <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
      <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap;padding:var(--space-3) 20px;border-bottom:1px solid var(--bg-hover)">
        <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:var(--space-2);margin:0">
          <span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--primary),var(--primary-accent));border-radius:var(--radius-md);font-size:var(--text-lg);color:white">📅</span>
          生产排程
        </h3>
        <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto">
          <select v-model="statusFilter" class="form-input" style="width:120px;padding:6px 10px;font-size:var(--text-sm)">
            <option value="all">全部状态</option>
            <option value="pending">待生产</option>
            <option value="producing">生产中</option>
            <option value="completed">已完成</option>
          </select>
          <button @click="zoomOut" title="缩小" class="btn-default btn-sm" style="font-size:var(--text-lg);padding:var(--space-1) 10px">−</button>
          <button @click="zoomIn" title="放大" class="btn-default btn-sm" style="font-size:var(--text-lg);padding:var(--space-1) 10px">+</button>
          <span style="color:var(--text-placeholder);font-size:var(--text-sm)">{{ filteredOrders.length }} 个订单</span>
        </div>
      </div>

      <div v-if="loading" style="text-align:center;padding:60px;color:var(--text-placeholder)">⏳ 加载中...</div>
      <div v-else-if="!filteredOrders.length" style="text-align:center;padding:60px;color:var(--text-placeholder)"><p style="font-size:48px;margin:0">📅</p><p style="margin-top:12px">暂无排程数据</p></div>
      <div v-else style="overflow-x:auto;border-top:1px solid var(--bg-hover)">
        <div style="display:flex;border-bottom:1px solid var(--border-light);position:sticky;top:0;background:var(--bg-table-header);z-index:2">
          <div style="min-width:180px;padding:var(--space-3) 14px;font-weight:600;color:var(--text-placeholder);font-size:var(--text-sm);border-right:1px solid var(--border-light);flex-shrink:0">订单</div>
          <div style="display:flex;flex:1;overflow:hidden">
            <div v-for="d in ganttData.days" :key="d.date" :style="{minWidth:dayWidth+'px',padding:'6px 2px',textAlign:'center',fontSize:'var(--text-xs-alt)',color:d.isToday?'var(--primary)':'var(--text-placeholder)',borderRight:'1px solid var(--bg-hover)',background:d.isToday?'var(--primary-light)':'',fontWeight:d.isToday?'600':'400',flexShrink:0}">{{ d.label }}</div>
          </div>
        </div>
        <div v-for="(o, i) in filteredOrders" :key="o.id" style="display:flex;border-bottom:1px solid var(--bg-hover);min-height:44px;align-items:center" :style="{background:i%2===0?'#fff':'var(--bg-table-stripe)'}">
          <div style="min-width:180px;padding:var(--space-2) 14px;border-right:1px solid var(--border-light);flex-shrink:0;display:flex;flex-direction:column;gap:var(--space-1)">
            <span style="font-size:var(--text-sm);font-weight:600;color:var(--primary)">{{ o.order_no }}</span>
            <span style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ o.product_name }} · {{ o.customer_name }}</span>
          </div>
          <div style="position:relative;flex:1;height:32px" :style="{minWidth:ganttData.totalDays*dayWidth+'px'}">
            <div :style="{position:'absolute',left:barLeft(o)+'px',width:Math.max(barWidth(o)-2,dayWidth-2)+'px',top:'4px',height:'24px',borderRadius:'5px',background:barColor(o.status),display:'flex',alignItems:'center',justifyContent:'center',fontSize:'var(--text-2xs)',color:'#fff',padding:'0 4px',overflow:'hidden',whiteSpace:'nowrap',fontWeight:'500'}">{{ o.progress }}%</div>
          </div>
        </div>
      </div>

      <div style="display:flex;gap:20px;padding:var(--space-3) 20px;font-size:var(--text-xs);color:var(--text-placeholder);border-top:1px solid var(--bg-hover)">
        <span><span style="display:inline-block;width:12px;height:12px;border-radius:var(--radius-sm);background:var(--info);margin-right:4px;vertical-align:middle"></span> 生产中</span>
        <span><span style="display:inline-block;width:12px;height:12px;border-radius:var(--radius-sm);background:var(--text-placeholder);margin-right:4px;vertical-align:middle"></span> 待生产</span>
        <span><span style="display:inline-block;width:12px;height:12px;border-radius:var(--radius-sm);background:#16a34a;margin-right:4px;vertical-align:middle"></span> 已完成</span>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export default {
  setup() {
    const orders = ref([])
    const loading = ref(true)
    const dayWidth = ref(38)
    const statusFilter = ref('all')

    // RBAC — reserved for future edit/create features

    const stats = computed(() => {
      const all = orders.value
      return {
        total: all.length,
        producing: all.filter(o => o.status === 'producing').length,
        pending: all.filter(o => o.status === 'pending').length,
        completed: all.filter(o => o.status === 'completed').length,
      }
    })

    const filteredOrders = computed(() => {
      if (statusFilter.value === 'all') return orders.value
      return orders.value.filter(o => o.status === statusFilter.value)
    })

    const ganttData = computed(() => {
      const list = filteredOrders.value
      if (!list.length) return { minDate: '', maxDate: '', totalDays: 0, days: [] }

      const min = dateRange.value.minDate
      const max = dateRange.value.maxDate
      if (!min || !max) return { minDate: '', maxDate: '', totalDays: 0, days: [] }

      const d1 = new Date(min), d2 = new Date(max)
      const totalDays = Math.max(Math.ceil((d2 - d1) / 86400000) + 1, 1)
      const days = []
      for (let i = 0; i < totalDays; i++) {
        const d = new Date(d1); d.setDate(d.getDate() + i)
        days.push({ date: d.toISOString().slice(0,10), label: `${d.getMonth()+1}/${d.getDate()}`, isToday: d.toDateString() === new Date().toDateString() })
      }
      return { minDate: min, maxDate: max, totalDays, days }
    })

    function barLeft(order) {
      const min = ganttData.value.minDate
      if (!min || !order.plan_start) return 0
      return Math.max(0, (new Date(order.plan_start) - new Date(min)) / 86400000) * dayWidth.value
    }

    function barWidth(order) {
      if (!order.plan_start || !order.plan_end) return dayWidth.value
      const days = Math.max(1, (new Date(order.plan_end) - new Date(order.plan_start)) / 86400000 + 1)
      return days * dayWidth.value
    }

    function barColor(status) {
      if (status === 'producing') return 'linear-gradient(135deg,#2563eb,#3b82f6)'
      if (status === 'completed') return 'linear-gradient(135deg,#16a34a,#22c55e)'
      return 'linear-gradient(135deg,#9ca3af,#b0b7c3)'
    }

    function statusLabel(s) {
      return { producing:'生产中', pending:'待生产', completed:'已完成' }[s] || s
    }

    const dateRange = ref({ minDate: '', maxDate: '' })

    async function load() {
      loading.value = true
      try {
        const r = await api.get('/api/schedule/gantt')
        if (r.ok) {
          orders.value = r.orders
          dateRange.value = { minDate: r.min_date || '', maxDate: r.max_date || '' }
        }
      } catch (e) { showToast('加载排程失败', 'error') }
      finally { loading.value = false }
    }

    function zoomIn() { dayWidth.value = Math.min(dayWidth.value + 6, 80) }
    function zoomOut() { dayWidth.value = Math.max(dayWidth.value - 6, 20) }

    onMounted(load)

    return { orders, stats, loading, dayWidth, statusFilter, filteredOrders, ganttData, barLeft, barWidth, barColor, statusLabel, zoomIn, zoomOut }
  }
}
</script>
