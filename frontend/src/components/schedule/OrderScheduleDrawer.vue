<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  order: { type: Object, default: null },
  operations: { type: Array, default: () => [] },
  revisions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  canAdjustPriority: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'retry', 'action'])
const drawerRef = ref(null)
const activeTab = ref('overview')
const previousFocus = ref(null)

const orderLabel = computed(() => props.order?.order_no || `订单 #${props.order?.id || '-'}`)
const riskLabel = computed(() => {
  const value = props.order?.risk_level || 'none'
  return ({ overdue: '已逾期', high: '高风险', medium: '中风险', low: '低风险', none: '正常' })[value] || value
})

function operationStatus(operation) {
  if (operation.status === 'blocked' || operation.schedule_status === 'blocked') return '阻断'
  if (operation.locked) return '已锁定'
  return operation.revision_status || '已排程'
}

function operationRisk(operation) {
  const value = operation.risk_level || 'none'
  return ({ overdue: '已逾期', high: '高风险', medium: '中风险', low: '低风险', none: '正常' })[value] || value
}

function sourceLabel(operation) {
  return ({
    product: '产品级标准',
    route: '路线版本通用标准',
    generic: '通用标准',
    outsourced: '外协/非排程',
    'route_version:product': '路线版本 · 产品专用',
    'route:product': '路线 · 产品专用',
    'process:product': '工序 · 产品专用',
    'route_version:generic': '路线版本 · 通用',
    'route:generic': '路线 · 通用',
    'process:generic': '工序 · 通用',
    execution_policy: '执行策略（外协/非排程）',
  })[operation.standard_match_scope] || operation.standard_match_scope || '未记录'
}

function priorityLabel(order) {
  const level = Number(order?.priority_level ?? order?.priority ?? 0)
  const label = level >= 1 && level <= 5 ? `P${level}` : '未设置'
  return order?.is_expedited ? `${label} · 加急` : label
}

function nodeLabel(operation) {
  const code = operation.node_code || operation.node_code_snapshot || ''
  const name = operation.node_name || operation.node_name_snapshot || ''
  return [code, name].filter(Boolean).join(' · ') || operation.production_node_id || '未分配'
}

function blockedReason(operation) {
  return operation.blocked_reason || operation.reason || operation.error_message || '前置条件不满足'
}

function focusFirst() {
  nextTick(() => drawerRef.value?.querySelector('button, [tabindex="0"]')?.focus())
}

function onKeydown(event) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !drawerRef.value) return
  const focusable = [...drawerRef.value.querySelectorAll('button, input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(node => !node.disabled && node.offsetParent !== null)
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function onOpen() {
  previousFocus.value = document.activeElement
  activeTab.value = 'overview'
  document.body.style.overflow = 'hidden'
  focusFirst()
}

function onClose() {
  document.body.style.overflow = ''
  previousFocus.value?.focus?.()
  previousFocus.value = null
}

function triggerAction(action, payload = {}) {
  emit('action', { action, order: props.order, ...payload })
}

onMounted(() => document.addEventListener('keydown', onKeydown))
watch(() => props.open, (isOpen, wasOpen) => {
  if (isOpen && !wasOpen) onOpen()
  if (!isOpen && wasOpen) onClose()
}, { immediate: true })
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="schedule-order-drawer__overlay" @click.self="emit('close')">
      <aside ref="drawerRef" class="schedule-order-drawer" role="dialog" aria-modal="true" :aria-label="`${orderLabel} 排程详情`">
        <header class="schedule-order-drawer__header">
          <div>
            <div class="schedule-order-drawer__eyebrow">生产排程 · 订单详情</div>
            <h2>{{ orderLabel }}</h2>
            <p>{{ order?.product_code || order?.product_name || '未填写产品' }} · 当前排程版本 {{ order?.schedule_revision_id || '未发布' }}</p>
          </div>
          <button type="button" class="btn-default" aria-label="关闭订单详情" @click="emit('close')">×</button>
        </header>

        <nav class="schedule-order-drawer__tabs" aria-label="订单详情页签">
          <button type="button" :class="{ active: activeTab === 'overview' }" @click="activeTab = 'overview'">概览</button>
          <button type="button" :class="{ active: activeTab === 'operations' }" @click="activeTab = 'operations'">工序进度 <span>{{ operations.length }}</span></button>
          <button type="button" :class="{ active: activeTab === 'revisions' }" @click="activeTab = 'revisions'">版本与审计 <span>{{ revisions.length }}</span></button>
        </nav>

        <main class="schedule-order-drawer__body">
          <div v-if="loading" class="schedule-order-drawer__state">正在加载订单排程详情…</div>
          <div v-else-if="error" class="schedule-order-drawer__state schedule-order-drawer__state--error" role="alert">
            <strong>订单详情加载失败</strong><span>{{ error }}</span><button type="button" class="btn-default btn-sm" @click="emit('retry')">重新加载</button>
          </div>

          <template v-else-if="order">
            <section v-if="activeTab === 'overview'" class="schedule-order-drawer__section">
              <div class="schedule-order-drawer__metric-grid">
                <div><span>订单状态</span><strong>{{ order.status || '-' }}</strong></div>
                <div><span>订单数量</span><strong>{{ order.quantity || 0 }}</strong></div>
                <div><span>已完成</span><strong>{{ order.completed_qty || order.completed || 0 }}</strong></div>
                <div><span>优先级</span><strong>{{ priorityLabel(order) }}</strong></div>
                <div><span>交期</span><strong>{{ order.deadline || order.deadline_at || '-' }}</strong></div>
                <div><span>风险</span><strong :class="`risk-${order.risk_level || 'none'}`">{{ riskLabel }}</strong></div>
              </div>
              <div class="schedule-order-drawer__callout" :class="{ danger: ['overdue', 'high'].includes(order.risk_level) }">
                <b>交期判断</b>
                <span>{{ order.risk_reason || '当前没有记录交期风险原因。' }}</span>
                <span v-if="Number(order.delay_minutes) > 0">预计延期 {{ order.delay_minutes }} 分钟</span>
              </div>
              <div class="schedule-order-drawer__actions">
                <button type="button" class="btn btn-primary" @click="triggerAction('replan')">模拟重排</button>
                <button v-if="canAdjustPriority" type="button" class="btn-default" @click="triggerAction('priority')">调整优先级</button>
                <button type="button" class="btn-default" @click="activeTab = 'operations'">查看工序进度</button>
              </div>
            </section>

            <section v-else-if="activeTab === 'operations'" class="schedule-order-drawer__section">
              <div v-if="!operations.length" class="schedule-order-drawer__empty">暂无工序排程记录</div>
              <article v-for="operation in operations" :key="operation.id || operation.order_process_id" class="schedule-order-drawer__operation">
                <div class="schedule-order-drawer__operation-head">
                  <strong>{{ operation.seq_order || operation.seq || '-' }} · {{ operation.process_name || `工序 #${operation.process_id}` }}</strong>
                  <span :class="`risk-${operation.risk_level || 'none'}`">{{ operationRisk(operation) }}</span>
                </div>
                <dl>
                  <div><dt>路线/工序版本</dt><dd>{{ operation.route_version_id || '-' }} / {{ operation.process_version_id || '-' }}</dd></div>
                  <div><dt>标准工时</dt><dd>{{ operation.standard_minutes_per_unit || 0 }} 分钟/件 · 准备 {{ operation.setup_minutes || 0 }} 分钟</dd></div>
                  <div><dt>工时来源</dt><dd>{{ sourceLabel(operation) }}</dd></div>
                  <div><dt>生产节点</dt><dd>{{ nodeLabel(operation) }}</dd></div>
                  <div><dt>预计时间</dt><dd>{{ operation.planned_start_at || operation.plan_start || '-' }} ~ {{ operation.planned_end_at || operation.plan_end || '-' }}</dd></div>
                  <div><dt>实际时间</dt><dd>{{ operation.actual_start_at || operation.actual_start || '未开始' }}<template v-if="operation.actual_end_at || operation.actual_end"> ~ {{ operation.actual_end_at || operation.actual_end }}（已完成）</template><template v-else-if="operation.actual_last_report_at"> ~ {{ operation.actual_last_report_at }}（最近报工）</template></dd></div>
                  <div><dt>状态</dt><dd :class="{ blocked: operation.status === 'blocked' || operation.schedule_status === 'blocked' }">{{ operationStatus(operation) }}<template v-if="operation.status === 'blocked' || operation.schedule_status === 'blocked'">：{{ blockedReason(operation) }}</template></dd></div>
                </dl>
                <div class="schedule-order-drawer__operation-actions">
                  <button type="button" class="btn-default btn-sm" @click="triggerAction('operation', { operation })">查看操作</button>
                </div>
              </article>
            </section>

            <section v-else class="schedule-order-drawer__section">
              <div v-if="!revisions.length" class="schedule-order-drawer__empty">暂无排程版本审计记录</div>
              <article v-for="revision in revisions" :key="revision.id" class="schedule-order-drawer__revision">
                <div><strong>第 {{ revision.revision_no || revision.id }} 版</strong><span>{{ revision.status || '-' }} / {{ revision.approval_status || '-' }}</span></div>
                <p>{{ revision.reason || revision.revision_reason || '未填写原因' }}</p>
                <small>{{ revision.created_at || revision.updated_at || '-' }} · 操作人 {{ revision.created_by_name || revision.created_by || '-' }}</small>
              </article>
            </section>
          </template>
        </main>

        <footer class="schedule-order-drawer__footer">
          <span>重要操作会生成排程审计记录，正式版本必须经过审批和发布。</span>
          <button type="button" class="btn-default" @click="emit('close')">关闭</button>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.schedule-order-drawer__overlay { position:fixed; inset:0; z-index:3200; background:rgb(15 23 42 / 45%); }
.schedule-order-drawer { position:absolute; top:0; right:0; display:flex; flex-direction:column; width:min(680px, 92vw); height:100%; background:var(--bg-surface); box-shadow:-18px 0 48px rgb(15 23 42 / 22%); }
.schedule-order-drawer__header { display:flex; justify-content:space-between; gap:16px; padding:20px 22px 16px; border-bottom:1px solid var(--border-light); }
.schedule-order-drawer__eyebrow { color:var(--primary); font-size:var(--text-xs); font-weight:700; }
.schedule-order-drawer h2 { margin:4px 0; font-size:var(--text-xl); }
.schedule-order-drawer p { margin:0; color:var(--text-secondary); font-size:var(--text-sm); }
.schedule-order-drawer__tabs { display:flex; gap:4px; padding:0 18px; border-bottom:1px solid var(--border-light); overflow:auto; }
.schedule-order-drawer__tabs button { border:0; border-bottom:2px solid transparent; background:transparent; padding:12px 10px; color:var(--text-secondary); white-space:nowrap; cursor:pointer; }
.schedule-order-drawer__tabs button.active { border-bottom-color:var(--primary); color:var(--primary); font-weight:700; }
.schedule-order-drawer__tabs span { margin-left:4px; color:var(--text-placeholder); }
.schedule-order-drawer__body { flex:1; overflow:auto; padding:18px 22px 26px; }
.schedule-order-drawer__state,.schedule-order-drawer__empty { display:grid; gap:8px; place-items:center; min-height:180px; color:var(--text-secondary); text-align:center; }
.schedule-order-drawer__state--error { color:var(--danger); }
.schedule-order-drawer__section { display:grid; gap:14px; }
.schedule-order-drawer__metric-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.schedule-order-drawer__metric-grid > div { display:flex; flex-direction:column; gap:4px; padding:11px 12px; border:1px solid var(--border-light); border-radius:var(--radius-sm); background:var(--bg-hover); }
.schedule-order-drawer__metric-grid span,.schedule-order-drawer dt { color:var(--text-placeholder); font-size:var(--text-xs); }
.schedule-order-drawer__metric-grid strong { color:var(--text-primary); font-size:var(--text-sm); }
.schedule-order-drawer__callout { display:grid; gap:4px; padding:12px 14px; border-left:3px solid var(--primary); background:var(--primary-light); font-size:var(--text-sm); }
.schedule-order-drawer__callout.danger { border-left-color:var(--danger); background:var(--danger-light); }
.schedule-order-drawer__actions,.schedule-order-drawer__operation-actions { display:flex; gap:8px; flex-wrap:wrap; }
.schedule-order-drawer__operation,.schedule-order-drawer__revision { padding:13px 14px; border:1px solid var(--border-light); border-radius:var(--radius-sm); }
.schedule-order-drawer__operation-head,.schedule-order-drawer__revision > div { display:flex; justify-content:space-between; gap:12px; align-items:center; }
.schedule-order-drawer__operation dl { display:grid; gap:7px; margin:12px 0; }
.schedule-order-drawer__operation dl > div { display:grid; grid-template-columns:110px minmax(0,1fr); gap:8px; }
.schedule-order-drawer dd { margin:0; color:var(--text-primary); font-size:var(--text-sm); }
.schedule-order-drawer dd.blocked { color:var(--danger); }
.schedule-order-drawer__revision p { margin:8px 0; }
.schedule-order-drawer__revision small { color:var(--text-placeholder); }
.schedule-order-drawer__footer { display:flex; justify-content:space-between; gap:12px; align-items:center; padding:12px 22px; border-top:1px solid var(--border-light); color:var(--text-placeholder); font-size:var(--text-xs); }
.risk-overdue,.risk-high { color:var(--danger) !important; }
.risk-medium { color:#b45309 !important; }
.risk-low { color:#65a30d !important; }
.risk-none { color:var(--success) !important; }
@media (max-width: 700px) {
  .schedule-order-drawer { width:100%; }
  .schedule-order-drawer__header,.schedule-order-drawer__body,.schedule-order-drawer__footer { padding-left:14px; padding-right:14px; }
  .schedule-order-drawer__metric-grid { grid-template-columns:1fr; }
  .schedule-order-drawer__footer { align-items:flex-start; flex-direction:column; }
}
</style>
