import { ref, computed, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV, statusLabel } from '@/composables/reports/reportSupport.js'

function statusBadge(s) {
  const map = { pending: 'badge-info', producing: 'badge-warning', completed: 'badge-success', paused: 'badge-info', cancelled: 'badge-danger' }
  return map[s] || 'badge-info'
}

export function useProgressStats(props) {
  const progressOrders = ref([])
  const progressStats = computed(() => {
    const data = progressOrders.value
    return {
      count: data.length,
      qty: data.reduce((s,o) => s+(o.quantity||0), 0),
      completed: data.reduce((s,o) => s+(o.completed||0), 0),
      near80: data.filter(o => {
        const pct = o.quantity>0 ? Math.round((o.completed||0)/o.quantity*100) : 0
        return pct >= 80
      }).length,
      pending: data.filter(o => o.status === 'pending').length,
    }
  })
  function progressPct(o) { return o.quantity>0 ? Math.min(Math.round((o.completed||0)/o.quantity*100),100) : 0 }
  function progressColor(o) { const p=progressPct(o); return p>=100?'var(--success)':p>=50?'var(--primary)':'var(--warning)' }

  async function loadProgress() {
    try {
      const params = {}
      if (props.start) params.start = props.start
      if (props.end) params.end = props.end
      if (props.productCode) params.product_code = props.productCode
      const d = await api.domains.stats.orderProgress(params)
      progressOrders.value = d.orders || []
    } catch (e) { showToast(e.message, 'error') }
  }

  function exportCsv() {
    if (!progressOrders.value.length) { showToast('没有数据可导出', 'warning'); return }
    const data = [['#','订单号','客户','产品','数量','已完成','进度','状态']]
    progressOrders.value.forEach((o,i) => {
      data.push([i+1, o.order_no, o.customer, o.product_name, o.quantity, o.completed, progressPct(o)+'%', statusLabel(o.status)])
    })
    exportCSV(data, '订单进度表')
  }

  watch(() => [props.start, props.end, props.productCode], loadProgress)
  onMounted(loadProgress)
  return { progressOrders, progressStats, progressPct, progressColor, statusLabel, statusBadge, exportCsv }
}
