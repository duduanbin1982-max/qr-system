<template>
  <div>
    <div class="card trace-card">
      <div class="card-header"><h3>📝 报工记录 ({{ workRecords.length }})</h3></div>
      <div class="card-body">
        <div v-if="workRecords.length" class="timeline">
          <div v-for="(record, index) in workRecords" :key="record.id" class="timeline-row">
            <div class="timeline-index">{{ index + 1 }}</div>
            <div class="timeline-content">
              <div class="timeline-title">
                <strong>{{ record.process_name || '-' }}</strong>
                <span class="badge" :class="workStatusClass(record.status)">{{ workStatusLabel(record.status) }}</span>
              </div>
              <div class="timeline-meta">
                <span>{{ record.worker_name || '-' }}</span><span>数量 {{ record.quantity }}</span>
                <span v-if="timeDiff(index)">⏱ {{ timeDiff(index) }}</span><span>{{ record.created_at }}</span>
              </div>
              <div v-if="record.remark" class="timeline-meta">备注：{{ record.remark }}</div>
            </div>
          </div>
        </div>
        <p v-else class="trace-empty">暂无报工记录</p>
      </div>
    </div>

    <div class="card trace-card">
      <div class="card-header"><h3>🕐 完整生命周期</h3></div>
      <div class="card-body timeline">
        <div v-if="result.order" class="timeline-row">
          <div class="timeline-icon">📋</div>
          <div><strong>订单创建</strong><div class="timeline-meta">{{ result.order.created_at }}</div></div>
        </div>
        <div v-for="(record, index) in workRecords" :key="`life-${record.id}`" class="timeline-row">
          <div class="timeline-index">{{ index + 1 }}</div>
          <div><strong>{{ record.process_name || '-' }}</strong><div class="timeline-meta">{{ record.worker_name || '-' }} · +{{ record.quantity }} · {{ record.created_at }}</div></div>
        </div>
        <div v-for="inspection in qualityInspections" :key="`quality-${inspection.id}`" class="timeline-row">
          <div class="timeline-icon">🔍</div>
          <div><strong>{{ inspection.process_name || '-' }} 质检</strong><div class="timeline-meta">{{ qualityResultLabel(inspection.result) }} · 抽检 {{ inspection.quantity_checked }} · {{ inspection.inspected_at || inspection.created_at }}</div></div>
        </div>
        <div v-for="log in inventoryLogs" :key="`inventory-${log.id}`" class="timeline-row">
          <div class="timeline-icon">📦</div>
          <div><strong>{{ result.item ? '订单入库' : '入库' }} · {{ log.product_name || log.product_model || '-' }}</strong><div class="timeline-meta">{{ log.type === 'in' ? '+' : '-' }}{{ log.quantity }} · {{ log.created_at }}</div></div>
        </div>
        <div v-for="shipment in shipments" :key="`shipment-${shipment.id}`" class="timeline-row">
          <div class="timeline-icon">🚚</div>
          <div><strong>{{ result.item ? '订单发货' : '发货' }} · {{ shipment.shipment_no }}</strong><div class="timeline-meta">数量 {{ shipment.order_quantity || shipment.total_quantity }} · {{ shipment.completed_at || shipment.created_at }}</div></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ result: { type: Object, required: true } })
const workRecords = computed(() => props.result.work_records || [])
const qualityInspections = computed(() => props.result.quality_inspections || [])
const inventoryLogs = computed(() => props.result.item ? props.result.order_scope?.inventory_logs || [] : props.result.inventory_logs || [])
const shipments = computed(() => props.result.item ? props.result.order_scope?.shipments || [] : props.result.shipments || [])

function timeDiff(index) {
  if (index === 0) return ''
  const previous = new Date(workRecords.value[index - 1]?.created_at).getTime()
  const current = new Date(workRecords.value[index]?.created_at).getTime()
  const difference = current - previous
  if (!Number.isFinite(difference) || difference < 0) return ''
  const hours = Math.floor(difference / 3600000)
  const minutes = Math.floor((difference % 3600000) / 60000)
  return hours ? `${hours}h${minutes ? `${minutes}m` : ''}` : `${minutes}min`
}

function workStatusLabel(status) {
  return status === 'approved' ? '已审批' : status === 'pending' ? '待审批' : status || '-'
}

function workStatusClass(status) {
  return status === 'approved' ? 'badge-success' : status === 'pending' ? 'badge-warning' : 'badge-danger'
}

function qualityResultLabel(result) {
  return ({ pass: '合格', rework: '返修', scrap: '报废', pending: '待检' })[result] || result || '-'
}
</script>

<style scoped>
.trace-card { margin-bottom: var(--space-5); }
.timeline-row { display: flex; gap: var(--space-4); align-items: flex-start; padding: var(--space-3) 0; border-bottom: 1px solid var(--bg-hover); }
.timeline-row:last-child { border-bottom: 0; }
.timeline-index, .timeline-icon { display: flex; width: 32px; height: 32px; flex: 0 0 32px; align-items: center; justify-content: center; border-radius: 50%; background: var(--primary-light); color: var(--primary); font-size: var(--text-xs); font-weight: 700; }
.timeline-content { flex: 1; min-width: 0; }
.timeline-title { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.timeline-meta { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: 3px; color: var(--text-placeholder); font-size: var(--text-xs); }
.trace-empty { padding: var(--space-5); color: var(--text-placeholder); text-align: center; }
</style>
