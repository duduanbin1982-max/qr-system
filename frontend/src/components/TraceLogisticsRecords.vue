<template>
  <div>
    <div class="card trace-card">
      <div class="card-header"><h3>🧱 {{ result.item ? '工件物料消耗' : '物料消耗' }} ({{ materials.length }})</h3></div>
      <div class="card-body trace-table-wrap">
        <MaterialTable v-if="materials.length" :records="materials" />
        <p v-else class="trace-empty">暂无物料消耗</p>
      </div>
    </div>

    <div v-if="result.item" class="card trace-card">
      <div class="card-header"><h3>订单级手工物料消耗 ({{ manualMaterials.length }})</h3></div>
      <div class="card-body trace-table-wrap">
        <MaterialTable v-if="manualMaterials.length" :records="manualMaterials" />
        <p v-else class="trace-empty">暂无订单级手工物料消耗</p>
      </div>
    </div>

    <div class="card trace-card">
      <div class="card-header"><h3>🔄 {{ result.item ? '订单级返工记录' : '返工记录' }} ({{ reworkRecords.length }})</h3></div>
      <div class="card-body trace-table-wrap">
        <table v-if="reworkRecords.length" class="data-table">
          <thead><tr><th>工序</th><th>数量</th><th>原因</th><th>操作人</th><th>状态</th><th>创建时间</th><th>完成时间</th></tr></thead>
          <tbody><tr v-for="record in reworkRecords" :key="record.id">
            <td>{{ record.process_name || '-' }}</td><td class="quantity-out">{{ record.quantity }}</td><td :title="record.reason">{{ record.reason || '-' }}</td>
            <td>{{ record.worker_name || '-' }}</td><td><span class="badge" :class="record.status === 'completed' ? 'badge-success' : 'badge-warning'">{{ record.status === 'completed' ? '已完成' : '处理中' }}</span></td>
            <td>{{ record.created_at }}</td><td>{{ record.completed_at || '-' }}</td>
          </tr></tbody>
        </table>
        <p v-else class="trace-empty">暂无返工记录</p>
      </div>
    </div>

    <div class="card trace-card">
      <div class="card-header"><h3>📦 {{ result.item ? '订单级库存流水' : '库存流水' }} ({{ inventoryLogs.length }})</h3></div>
      <div class="card-body trace-table-wrap">
        <table v-if="inventoryLogs.length" class="data-table">
          <thead><tr><th>产品编码</th><th>产品名称</th><th>类型</th><th>数量</th><th>操作人</th><th>备注</th><th>时间</th></tr></thead>
          <tbody><tr v-for="log in inventoryLogs" :key="log.id">
            <td><code>{{ log.product_model || '-' }}</code></td><td>{{ log.product_name || '-' }}</td>
            <td><span class="badge" :class="log.type === 'in' ? 'badge-success' : 'badge-warning'">{{ log.type === 'in' ? '入库' : '出库' }}</span></td>
            <td>{{ log.quantity }}</td><td>{{ log.operator_name || '-' }}</td><td>{{ log.remark || '-' }}</td><td>{{ log.created_at }}</td>
          </tr></tbody>
        </table>
        <p v-else class="trace-empty">暂无库存流水</p>
      </div>
    </div>

    <div class="card trace-card">
      <div class="card-header"><h3>🚚 {{ result.item ? '订单级发货记录' : '发货记录' }} ({{ shipments.length }})</h3></div>
      <div class="card-body trace-table-wrap">
        <table v-if="shipments.length" class="data-table">
          <thead><tr><th>出库单号</th><th>客户</th><th>状态</th><th>订单数量</th><th>出库单总量</th><th>出库时间</th></tr></thead>
          <tbody><tr v-for="shipment in shipments" :key="shipment.id">
            <td><code>{{ shipment.shipment_no }}</code></td><td>{{ shipment.customer || '-' }}</td>
            <td><span class="badge" :class="shipment.status === 'completed' ? 'badge-success' : 'badge-info'">{{ shipment.status === 'completed' ? '已出库' : '待出库' }}</span></td>
            <td>{{ shipment.order_quantity || shipment.total_quantity }}</td><td>{{ shipment.total_quantity }}</td><td>{{ shipment.completed_at || shipment.created_at || '-' }}</td>
          </tr></tbody>
        </table>
        <p v-else class="trace-empty">暂无发货记录</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h } from 'vue'

const props = defineProps({ result: { type: Object, required: true } })
const materials = computed(() => props.result.material_consumptions || [])
const manualMaterials = computed(() => props.result.item ? props.result.order_scope?.manual_material_consumptions || [] : [])
const reworkRecords = computed(() => props.result.item ? props.result.order_scope?.rework_records || [] : props.result.rework_records || [])
const inventoryLogs = computed(() => props.result.item ? props.result.order_scope?.inventory_logs || [] : props.result.inventory_logs || [])
const shipments = computed(() => props.result.item ? props.result.order_scope?.shipments || [] : props.result.shipments || [])

const MaterialTable = defineComponent({
  props: { records: { type: Array, required: true } },
  setup(tableProps) {
    return () => h('table', { class: 'data-table material-table' }, [
      h('thead', h('tr', ['物料', '规格', '工序', '数量', '操作人', '备注', '时间'].map(label => h('th', label)))),
      h('tbody', tableProps.records.map(record => h('tr', { key: record.id }, [
        h('td', record.material_name || '-'), h('td', record.material_spec || '-'), h('td', record.process_name || '-'),
        h('td', { class: 'quantity-out' }, record.quantity), h('td', record.operator_name || '-'),
        h('td', { title: record.notes || '' }, record.notes || '-'), h('td', record.created_at || '-'),
      ]))),
    ])
  },
})
</script>

<style scoped>
.trace-card { margin-bottom: var(--space-5); }
.trace-table-wrap { overflow-x: auto; }
.data-table { min-width: 760px; font-size: var(--text-xs); }
.material-table { min-width: 820px; }
.quantity-out { color: var(--danger); font-weight: 600; }
.trace-empty { padding: var(--space-5); color: var(--text-placeholder); text-align: center; }
</style>
