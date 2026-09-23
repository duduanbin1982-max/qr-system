<script setup>
import { computed, ref, watch } from 'vue'
import { scheduleSegments, sortScheduleSegments } from '@/composables/gantt/useScheduleSegments.js'

const props = defineProps({
  operations: { type: Array, default: () => [] },
  nodes: { type: Array, default: () => [] },
  orders: { type: Array, default: () => [] },
})
const emit = defineEmits(['open-order', 'filter-node'])
const selectedProcessKey = ref('')
const selectedNodeId = ref('')

const processGroups = computed(() => {
  const byProcess = new Map()
  props.nodes.forEach(node => {
    const key = String(node.process_id || node.process_name || 'unknown')
    if (!byProcess.has(key)) byProcess.set(key, { key, name: node.process_name || `工序 #${node.process_id}`, nodes: [] })
    byProcess.get(key).nodes.push(node)
  })
  return [...byProcess.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})

const activeProcessGroup = computed(() => processGroups.value.find(group => group.key === selectedProcessKey.value) || processGroups.value[0] || null)
const activeNodes = computed(() => activeProcessGroup.value?.nodes || [])
const activeNode = computed(() => activeNodes.value.find(node => String(node.id) === String(selectedNodeId.value)) || activeNodes.value[0] || null)

watch(processGroups, (groups) => {
  if (!groups.some(group => group.key === selectedProcessKey.value)) selectedProcessKey.value = groups[0]?.key || ''
}, { immediate: true })
watch(activeNodes, (nodes) => {
  if (!nodes.some(node => String(node.id) === String(selectedNodeId.value))) selectedNodeId.value = nodes[0]?.id || ''
}, { immediate: true })

function nodeOperations(node) {
  return sortScheduleSegments(props.operations
    .flatMap(operation => scheduleSegments(operation))
    .filter(segment => String(segment.production_node_id || '') === String(node.id)))
}

function orderLabel(operation) {
  return operation.order_no || `订单 #${operation.order_id}`
}

function orderFor(operation) {
  return props.orders.find(order => String(order.id) === String(operation.order_id)) || { id: operation.order_id, order_no: orderLabel(operation) }
}

function selectNode(node) {
  selectedNodeId.value = node.id
  emit('filter-node', node.id)
}
</script>

<template>
  <section class="production-node-queue" data-test="production-node-queue-board">
    <header><div><h5>节点排队看板</h5><p>按工序查看每个生产节点的当前任务、下一任务和风险；点击任务可打开订单详情。</p></div><span>同类节点可互换 · 正式调整仍需审批</span></header>
    <div v-if="!processGroups.length" class="queue-empty">当前没有可展示的生产节点</div>
    <div v-else class="queue-three-column">
      <aside class="queue-process-list" aria-label="工序列表">
        <div class="queue-column-title">工序</div>
        <button v-for="group in processGroups" :key="group.key" type="button" :class="{ active: group.key === activeProcessGroup?.key }" @click="selectedProcessKey = group.key">
          <strong>{{ group.name }}</strong><span>{{ group.nodes.length }} 个节点</span>
        </button>
      </aside>
      <main class="queue-node-list" aria-label="生产节点列表">
        <div class="queue-column-title">生产节点 · {{ activeProcessGroup?.name }}</div>
        <article v-for="node in activeNodes" :key="node.id" class="queue-node-card" :class="{ active: String(node.id) === String(activeNode?.id) }" @click="selectNode(node)">
          <header><div><b>{{ node.node_code || `NODE-${node.id}` }}</b><span>{{ node.node_name || '-' }}</span></div><em>{{ node.status || 'active' }}</em></header>
          <div class="queue-node-summary"><strong>{{ nodeOperations(node).length }}</strong><span>条排队任务</span></div>
          <footer><span>容量 {{ node.capacity_minutes || 0 }} 分钟</span><button type="button" class="btn-default btn-sm" @click.stop="selectNode(node)">查看时间轴</button></footer>
        </article>
      </main>
      <aside class="queue-timeline" aria-label="节点时间轴">
        <div class="queue-column-title">时间轴 · {{ activeNode?.node_code || '未选择节点' }}</div>
        <div v-if="activeNode && nodeOperations(activeNode).length" class="queue-node-tasks">
          <button v-for="(operation, index) in nodeOperations(activeNode)" :key="operation.key" type="button" class="queue-task" @click="emit('open-order', orderFor(operation))">
            <span class="queue-task-index">{{ index === 0 ? '当前' : index === 1 ? '下一' : '后续' }}</span>
            <strong>{{ orderLabel(operation) }}</strong>
            <small>{{ operation.process_name || activeProcessGroup?.name }} · {{ operation.planned_start_at || '待定' }} ~ {{ operation.planned_end_at || '待定' }} · {{ operation.quantity || 0 }} 件 · {{ Math.round(operation.occupied_minutes || 0) }} 分钟</small>
            <small v-if="operation.status === 'blocked' || operation.schedule_status === 'blocked'" class="danger">阻断：{{ operation.blocked_reason || operation.reason || '前置条件不满足' }}</small>
          </button>
        </div>
        <div v-else class="queue-node-idle">该节点暂无排队任务</div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.production-node-queue { display:grid; gap:12px; margin-top:14px; }
.production-node-queue > header { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; padding:12px 14px; border:1px solid var(--border-light); border-radius:var(--radius-sm); background:var(--bg-hover); }
.production-node-queue h5 { margin:0; font-size:var(--text-sm); }
.production-node-queue p,.production-node-queue header span { margin:4px 0 0; color:var(--text-secondary); font-size:var(--text-xs); }
.queue-three-column { display:grid; grid-template-columns:180px minmax(230px, 1fr) minmax(300px, 1.4fr); gap:10px; min-height:260px; }
.queue-process-list,.queue-node-list,.queue-timeline { display:flex; flex-direction:column; gap:7px; min-width:0; padding:9px; border:1px solid var(--border-light); border-radius:var(--radius-sm); background:var(--bg-surface); }
.queue-column-title { padding:3px 4px 7px; border-bottom:1px solid var(--border-light); color:var(--text-secondary); font-size:var(--text-xs); font-weight:700; }
.queue-process-list button { display:flex; justify-content:space-between; gap:5px; width:100%; padding:9px 8px; border:1px solid transparent; border-radius:4px; background:transparent; color:var(--text-primary); text-align:left; cursor:pointer; }
.queue-process-list button span { color:var(--text-placeholder); font-size:10px; }
.queue-process-list button.active { border-color:var(--primary); background:var(--primary-light); color:var(--primary); }
.queue-node-list { overflow:auto; }
.queue-node-card { display:flex; flex-direction:column; gap:8px; padding:10px; border:1px solid var(--border-light); border-radius:var(--radius-sm); background:var(--bg-surface); cursor:pointer; }
.queue-node-card.active { border-color:var(--primary); box-shadow:0 0 0 2px color-mix(in srgb, var(--primary) 15%, transparent); }
.queue-node-card > header,.queue-node-card > footer { display:flex; justify-content:space-between; gap:8px; align-items:center; }
.queue-node-card > header div { display:grid; gap:2px; }
.queue-node-card > header span,.queue-node-card > footer { color:var(--text-secondary); font-size:var(--text-xs); }
.queue-node-card > header em { color:var(--success); font-size:var(--text-xs); font-style:normal; }
.queue-node-summary { display:flex; align-items:baseline; gap:6px; color:var(--text-secondary); font-size:var(--text-xs); }
.queue-node-summary strong { color:var(--primary); font-size:var(--text-lg); }
.queue-node-tasks { display:grid; gap:5px; overflow:auto; }
.queue-task { display:grid; grid-template-columns:auto 1fr; gap:2px 6px; padding:7px 8px; border:1px solid var(--border-light); border-radius:4px; background:var(--bg-hover); text-align:left; cursor:pointer; }
.queue-task strong,.queue-task small { grid-column:2; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.queue-task-index { grid-row:1 / span 3; align-self:start; color:var(--primary); font-size:10px; font-weight:700; }
.queue-task small { color:var(--text-secondary); font-size:10px; }
.queue-task .danger,.danger { color:var(--danger); }
.queue-node-idle,.queue-empty { padding:20px; color:var(--text-placeholder); text-align:center; font-size:var(--text-xs); }
@media (max-width:900px) { .queue-three-column { grid-template-columns:150px minmax(210px,1fr); } .queue-timeline { grid-column:1 / -1; } }
@media (max-width:700px) { .production-node-queue > header { flex-direction:column; } .queue-three-column { grid-template-columns:1fr; } .queue-process-list,.queue-node-list,.queue-timeline { max-height:none; } }
</style>
