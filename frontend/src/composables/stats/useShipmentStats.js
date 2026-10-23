import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, buildParams, statusLabel, exportCSV } from '@/composables/reports/reportSupport.js'

export function useShipmentStats(props) {
  const shipmentByStatus = ref([]); const shipmentByCustomer = ref([]); const shipmentMonthly = ref([])
  const loading = ref(false); const updateTime = ref('')
  const load = createLoader(loading, updateTime, async () => {
    const d = await api.domains.stats.reportShipmentStats(buildParams(props.start, props.end, props.productCode || ''))
    shipmentByStatus.value = d.by_status || []; shipmentByCustomer.value = d.by_customer || []; shipmentMonthly.value = d.monthly_trend || []
  })

  function exportCsv(type) {
    const dateTag = (props.start || '') + '_' + (props.end || '')
    if (type === 'status') {
      if (!shipmentByStatus.value.length) { return }
      const data = [['状态','发货数','总数量']]
      shipmentByStatus.value.forEach(s => data.push([statusLabel(s.status,'shipment'), s.count, s.total_qty]))
      exportCSV(data, '发货统计_状态_' + dateTag)
    } else if (type === 'customer') {
      if (!shipmentByCustomer.value.length) { return }
      const data = [['客户','发货批次','总数量']]
      shipmentByCustomer.value.forEach(c => data.push([c.customer, c.shipment_count, c.total_qty]))
      exportCSV(data, '发货统计_客户_' + dateTag)
    } else if (type === 'monthly') {
      if (!shipmentMonthly.value.length) { return }
      const data = [['月份','发货批次','总数量']]
      shipmentMonthly.value.forEach(m => data.push([m.month, m.count, m.total_qty]))
      exportCSV(data, '发货统计_月度_' + dateTag)
    }
  }

  watch(() => [props.start, props.end, props.productCode], load)
  onMounted(load)
  return { shipmentByStatus, shipmentByCustomer, shipmentMonthly, exportCsv, statusLabel }
}
