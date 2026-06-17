<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">发货统计</span>
        <div style="display:flex;gap:var(--space-2)">
          <button class="btn btn-outline btn-sm" @click="exportCsv('status')" :disabled="!shipmentByStatus.length">📥 状态</button>
          <button class="btn btn-outline btn-sm" @click="exportCsv('customer')" :disabled="!shipmentByCustomer.length">📥 客户</button>
          <button class="btn btn-outline btn-sm" @click="exportCsv('monthly')" :disabled="!shipmentMonthly.length">📥 月度</button>
        </div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4)">
      <div class="card"><div class="card-header"><h3>📊 状态分布</h3></div>
        <div class="card-body">
          <div v-if="shipmentByStatus.length">
            <div v-for="s in shipmentByStatus" :key="s.status" style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:10px;padding:var(--space-2) 12px;background:var(--bg-table-header);border-radius:var(--radius-md)">
              <span class="badge" style="min-width:70px;text-align:center" :class="s.status==='completed'?'badge-success':s.status==='pending'?'badge-warning':'badge-info'">{{ statusLabel(s.status, 'shipment') }}</span>
              <span style="font-weight:600;font-size:var(--text-base);color:var(--primary)">{{ s.count }} 批</span>
              <span style="font-size:var(--text-sm);color:var(--text-placeholder)">数量 {{ s.total_qty }}</span>
            </div>
          </div>
          <p v-else class="empty"><span class="empty-text">无发货数据</span></p>
        </div>
      </div>
      <div class="card"><div class="card-header"><h3>🏢 按客户分析</h3></div>
        <div class="card-body"><div class="table-wrap"><table v-if="shipmentByCustomer.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr><th>客户</th><th>发货批次</th><th>总数量</th></tr></thead>
          <tbody><tr v-for="(c,i) in shipmentByCustomer" :key="i">
            <td style="font-weight:500">{{ c.customer }}</td>
            <td style="color:var(--primary);font-weight:600">{{ c.shipment_count }}</td>
            <td>{{ c.total_qty }}</td>
          </tr></tbody>
        </table><p v-else class="empty"><span class="empty-text">无数据</span></p></div></div>
      </div>
    </div>
    <div class="card" style="margin-top:var(--space-4)"><div class="card-header"><h3>📅 月度发货趋势</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="shipmentMonthly.length" class="data-table">
        <thead><tr><th>月份</th><th>发货批次</th><th>总数量</th></tr></thead>
        <tbody><tr v-for="m in shipmentMonthly" :key="m.month">
          <td style="font-weight:500">{{ m.month }}</td>
          <td style="color:var(--primary);font-weight:600">{{ m.count }}</td>
          <td>{{ m.total_qty }}</td>
        </tr></tbody>
      </table><p v-else class="empty"><span class="empty-text">无月度数据</span></p></div></div>
    </div>
  </div>
</template>
<script>
import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { createLoader, buildParams, statusLabel, exportCSV } from './shared.js'
export default {
  props: { start: String, end: String, productCode: String },
  setup(props) {
    const shipmentByStatus = ref([]); const shipmentByCustomer = ref([]); const shipmentMonthly = ref([])
    const loading = ref(false); const updateTime = ref('')
    const load = createLoader(loading, updateTime, async () => {
      const d = await api.shipmentStats(buildParams(props.start, props.end, props.productCode || ''))
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
}
</script>
