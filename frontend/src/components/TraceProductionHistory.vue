<template>
  <div>
    <div class="card trace-card">
      <div class="card-header"><h3>📝 报工记录 ({{ workRecords.length }})</h3></div>
      <div class="card-body">
        <div v-if="workRecords.length" class="timeline">
          <div v-for="(record, index) in workRecords" :key="JSON.stringify([record.id, index])" class="timeline-row">
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
      <div class="card-body timeline" data-testid="trace-lifecycle">
        <div v-for="event in lifecycleEvents" :key="event.key" class="timeline-row" :data-kind="event.kind">
          <div v-if="event.kind === 'work'" class="timeline-index">{{ event.ordinal }}</div>
          <div v-else class="timeline-icon">{{ eventIcons[event.kind] }}</div>
          <div>
            <strong>{{ event.label }}</strong>
            <div class="timeline-meta">
              <span v-if="event.kind === 'work'">{{ event.payload.worker_name || '-' }} · +{{ event.payload.quantity }} ·</span>
              <span v-else-if="event.kind === 'quality'">{{ qualityResultLabel(event.payload.result) }} · 抽检 {{ event.payload.quantity_checked }} ·</span>
              <span v-else-if="event.kind === 'inventory'">{{ event.payload.type === 'in' ? '+' : '-' }}{{ event.payload.quantity }} ·</span>
              <span v-else-if="event.kind === 'shipment'">数量 {{ event.payload.order_quantity || event.payload.total_quantity }} ·</span>
              <span>{{ event.time_label }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { buildTraceTimeline } from '@/lib/traceTimeline.js'

const props = defineProps({ result: { type: Object, required: true } })
const workRecords = computed(() => props.result.work_records || [])
const lifecycleEvents = computed(() => buildTraceTimeline(props.result))
const eventIcons = Object.freeze({ order: '📋', quality: '🔍', inventory: '📦', shipment: '🚚' })

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
