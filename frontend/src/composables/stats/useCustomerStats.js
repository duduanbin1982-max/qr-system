import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV } from '@/composables/reports/reportSupport.js'

export function useCustomerStats(props) {
  const customers = ref([])
  async function load() {
    try {
      const params = {}
      if (props.start) params.start = props.start
      if (props.end) params.end = props.end
      const d = await api.domains.stats.customerStats(params)
      customers.value = d || []
    } catch(e) { showToast(e.message, 'error') }
  }
  function exportCsv() {
    if (!customers.value.length) return
    const data = [['客户','订单数','总数量','已完成','生产中','完成率']]
    customers.value.forEach(c => data.push([c.customer_name,c.order_count,c.total_qty,c.completed_qty,c.active_orders,(c.total_qty>0?Math.round(c.completed_qty/c.total_qty*100):0)+'%']))
    const dt = props.start ? props.start + '_' + (props.end||'') : new Date().toISOString().slice(0,10); exportCSV(data, '客户统计_' + dt)
  }
  watch(() => [props.start, props.end], load)
  onMounted(load)
  return { customers, exportCsv }
}
