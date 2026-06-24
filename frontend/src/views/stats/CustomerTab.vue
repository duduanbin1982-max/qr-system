<template>
  <div>
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header"><h3>🏢 客户统计</h3><button class="btn btn-success btn-sm" @click="exportCsv" :disabled="!customers.length">📥 CSV</button></div>
    </div>
    <div class="card"><div class="card-header"><h3>📋 客户订单汇总</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="customers.length" class="data-table">
        <thead><tr><th>#</th><th>客户名称</th><th style="text-align:center">订单数</th><th style="text-align:center">总数量</th><th style="text-align:center">已完成</th><th style="text-align:center">生产中</th><th style="text-align:center">完成率</th></tr></thead>
        <tbody><tr v-for="(c,i) in customers" :key="i">
          <td>{{ i+1 }}</td><td style="font-weight:500">{{ c.customer_name }}</td>
          <td style="text-align:center">{{ c.order_count }}</td>
          <td style="text-align:center;font-weight:600">{{ c.total_qty }}</td>
          <td style="text-align:center;color:var(--success)">{{ c.completed_qty }}</td>
          <td style="text-align:center;color:var(--primary)">{{ c.active_orders }}</td>
          <td style="text-align:center">
            <div style="display:flex;align-items:center;gap:6px">
              <div style="flex:1;height:6px;background:var(--bg-table-header);border-radius:3px;overflow:hidden">
                <div :style="{width: c.total_qty>0 ? Math.round(c.completed_qty/c.total_qty*100)+'%' : '0%',height:'100%',background:'var(--success)',borderRadius:'3px'}"></div>
              </div>
              <span style="font-size:11px;color:var(--text-placeholder)">{{ c.total_qty>0 ? Math.round(c.completed_qty/c.total_qty*100) : 0 }}%</span>
            </div>
          </td>
        </tr></tbody>
      </table><p v-else class="empty">📭 暂无客户数据</p></div></div>
    </div>
  </div>
</template>
<script>
import { ref, watch, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { exportCSV } from './shared.js'
export default {
  props: { start: String, end: String },
  setup(props) {
    const customers = ref([])
    async function load() {
      try {
        const params = {}
        if (props.start) params.start = props.start
        if (props.end) params.end = props.end
        const d = await api.customerStats(params)
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
}
</script>