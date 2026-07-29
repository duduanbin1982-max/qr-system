<template>
  <div>
    <TraceTableCard title="质量任务" :count="tasks.length" :empty="!tasks.length" empty-text="暂无质量任务">
      <table class="data-table">
        <thead><tr><th>任务号</th><th>工序</th><th>类型</th><th>标准</th><th>门禁</th><th>抽样</th><th>状态</th><th>期限</th></tr></thead>
        <tbody><tr v-for="task in tasks" :key="task.id">
          <td><code>{{ task.task_no }}</code></td><td>{{ task.process_name || '-' }}</td><td>{{ task.inspection_type || '-' }}</td>
          <td>{{ task.standard_no || '-' }}</td><td>{{ gateLabel(task.gate_mode) }}</td><td>{{ task.sample_qty }}</td>
          <td><span class="badge" :class="taskStatusClass(task.status)">{{ taskStatusLabel(task.status) }}</span></td><td>{{ task.due_at || '-' }}</td>
        </tr></tbody>
      </table>
    </TraceTableCard>

    <TraceTableCard title="🔍 质检记录" :count="inspections.length" :empty="!inspections.length" empty-text="暂无质检记录">
      <table class="data-table">
        <thead><tr><th>序列号</th><th>工序</th><th>类型</th><th>抽检</th><th>合格</th><th>不合格</th><th>结果</th><th>检验员</th><th>时间</th></tr></thead>
        <tbody><tr v-for="inspection in inspections" :key="inspection.id">
          <td><code>{{ inspection.serial_no || '-' }}</code></td><td>{{ inspection.process_name || '-' }}</td><td>{{ inspection.inspection_type || '-' }}</td>
          <td>{{ inspection.quantity_checked }}</td><td class="text-success">{{ inspection.quantity_passed }}</td><td class="text-danger">{{ inspection.quantity_failed }}</td>
          <td><span class="badge" :class="qualityResultClass(inspection.result)">{{ qualityResultLabel(inspection.result) }}</span></td>
          <td>{{ inspection.inspector_name || '-' }}</td><td>{{ inspection.inspected_at || inspection.created_at }}</td>
        </tr></tbody>
      </table>
    </TraceTableCard>

    <TraceTableCard title="不合格品闭环" :count="nonconformances.length" :empty="!nonconformances.length" empty-text="暂无不合格品记录">
      <table class="data-table">
        <thead><tr><th>不合格单</th><th>序列号</th><th>工序</th><th>等级</th><th>数量</th><th>处置</th><th>状态</th><th>责任人</th><th>措施</th></tr></thead>
        <tbody><tr v-for="record in nonconformances" :key="record.id">
          <td><code>{{ record.ncr_no }}</code></td><td><code>{{ record.serial_no || '-' }}</code></td><td>{{ record.process_name || '-' }}</td>
          <td>{{ record.defect_level || '-' }}</td><td>{{ record.defect_quantity }}</td><td>{{ dispositionLabel(record.disposition) }}</td>
          <td><span class="badge" :class="record.status === 'closed' ? 'badge-success' : 'badge-warning'">{{ record.status === 'closed' ? '已关闭' : '处理中' }}</span></td>
          <td>{{ record.owner_name || '-' }}</td><td>{{ record.action_count || 0 }}</td>
        </tr></tbody>
      </table>
    </TraceTableCard>

    <TraceTableCard v-if="capa.length" title="纠正预防措施" :count="capa.length">
      <table class="data-table">
        <thead><tr><th>CAPA 编号</th><th>来源</th><th>标题</th><th>负责人</th><th>期限</th><th>状态</th><th>验证结果</th></tr></thead>
        <tbody><tr v-for="record in capa" :key="record.id">
          <td><code>{{ record.capa_no }}</code></td><td>{{ record.ncr_no || '-' }}</td><td>{{ record.title }}</td>
          <td>{{ record.owner_name || '-' }}</td><td>{{ record.due_at || '-' }}</td>
          <td><span class="badge" :class="record.status === 'closed' || record.status === 'verified' ? 'badge-success' : 'badge-warning'">{{ record.status }}</span></td>
          <td>{{ record.effectiveness_result || '-' }}</td>
        </tr></tbody>
      </table>
    </TraceTableCard>
  </div>
</template>

<script setup>
import { computed, defineComponent, h } from 'vue'

const props = defineProps({ result: { type: Object, required: true } })
const tasks = computed(() => props.result.quality_tasks || [])
const inspections = computed(() => props.result.quality_inspections || [])
const nonconformances = computed(() => props.result.quality_nonconformances || [])
const capa = computed(() => props.result.quality_capa || [])

const TraceTableCard = defineComponent({
  props: {
    title: { type: String, required: true },
    count: { type: Number, default: 0 },
    empty: { type: Boolean, default: false },
    emptyText: { type: String, default: '' },
  },
  setup(cardProps, { slots }) {
    return () => h('div', { class: 'card trace-card' }, [
      h('div', { class: 'card-header' }, h('h3', `${cardProps.title} (${cardProps.count})`)),
      h('div', { class: 'card-body trace-table-wrap' }, cardProps.empty
        ? h('p', { class: 'trace-empty' }, cardProps.emptyText)
        : slots.default?.()),
    ])
  },
})

function gateLabel(value) { return value === 'hard' ? '强拦截' : value === 'soft' ? '软提示' : '关闭' }
function taskStatusLabel(value) { return ({ pending: '待检', in_progress: '检验中', passed: '已通过', failed: '不合格', cancelled: '已取消' })[value] || value || '-' }
function taskStatusClass(value) { return value === 'passed' ? 'badge-success' : value === 'failed' || value === 'cancelled' ? 'badge-danger' : 'badge-warning' }
function qualityResultLabel(value) { return ({ pass: '合格', rework: '返修', scrap: '报废', pending: '待检' })[value] || value || '-' }
function qualityResultClass(value) { return value === 'pass' ? 'badge-success' : value === 'rework' || value === 'scrap' ? 'badge-danger' : 'badge-warning' }
function dispositionLabel(value) { return ({ pending: '待处置', rework: '返修', scrap: '报废', concession: '让步接收', isolate: '隔离', return: '退货' })[value] || value || '-' }
</script>

<style scoped>
.trace-card { margin-bottom: var(--space-5); }
.trace-table-wrap { overflow-x: auto; }
.data-table { min-width: 880px; font-size: var(--text-xs); }
.trace-empty { padding: var(--space-5); color: var(--text-placeholder); text-align: center; }
.text-danger { color: var(--danger); }
</style>
