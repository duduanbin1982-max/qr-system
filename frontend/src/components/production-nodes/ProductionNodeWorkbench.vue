<script setup>
import { computed, nextTick, onBeforeUnmount, ref, unref, watch } from 'vue'

import NodeCapabilityPanel from './NodeCapabilityPanel.vue'
import NodeCalendarPanel from './NodeCalendarPanel.vue'
import NodeEditorPanel from './NodeEditorPanel.vue'
import NodeListPanel from './NodeListPanel.vue'
import { PRODUCTION_NODE_TABS, useProductionNodeWorkbench } from '@/composables/gantt/useProductionNodeWorkbench.js'

const props = defineProps({
  modelValue: Boolean,
  manager: { type: Object, required: true },
  processOptions: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'closed'])
const dialogRef = ref(null)
const titleRef = ref(null)
const discardDialogRef = ref(null)
const tabRefs = ref([])
let returnFocus = null
let previousBodyOverflow = ''
let ownsBodyScrollLock = false
let discardReturnFocus = null

const state = props.manager.state
const actions = props.manager.actions
const permissions = props.manager.permissions
const productionNodes = computed(() => unref(state.productionNodes) || [])
const productionCalendars = computed(() => unref(state.productionCalendars) || [])
const currentNodeId = state.currentNodeId || ref(null)
const calendarsLoading = computed(() => Boolean(unref(state.calendarsLoading)))
const calendarsError = computed(() => String(unref(state.calendarsError) || ''))
const nodeSummary = computed(() => unref(state.nodeSummary) || {})
const nodeSummaryLoading = computed(() => Boolean(unref(state.nodeSummaryLoading)))
const nodeSummaryError = computed(() => String(unref(state.nodeSummaryError) || ''))
const nodesLoading = computed(() => Boolean(unref(state.nodesLoading)))
const nodesError = computed(() => String(unref(state.nodesError) || ''))
const nodeForm = computed(() => unref(state.nodeForm) || {})
const nodeSaving = computed(() => Boolean(unref(state.nodeSaving)))
const overrideForm = computed(() => unref(state.overrideForm) || {})
const nodeOverrides = computed(() => unref(state.nodeOverrides) || [])
const overridesLoading = computed(() => Boolean(unref(state.overridesLoading)))
const overridesError = computed(() => String(unref(state.overridesError) || ''))
const overrideSaving = computed(() => Boolean(unref(state.overrideSaving)))
const capabilityForm = computed(() => unref(state.capabilityForm) || { capabilities: [] })
const capabilitiesLoading = computed(() => Boolean(unref(state.capabilitiesLoading)))
const capabilitiesError = computed(() => String(unref(state.capabilitiesError) || ''))
const capabilitySaving = computed(() => Boolean(unref(state.capabilitySaving)))
const canManageNodes = computed(() => Boolean(unref(permissions.canManageNodes)))
const canManageCalendars = computed(() => Boolean(unref(permissions.canManageCalendars)))
const canManageCapabilities = computed(() => Boolean(unref(permissions.canManageCapabilities)))

function closeWorkbench() {
  actions.resetWorkbenchSession?.()
  workbench.resetSession()
  emit('update:modelValue', false)
  emit('closed')
}

async function enterTab(tab, node) {
  if (!node) return
  if (tab === 'list') {
    await actions.loadNodeSummary?.(node)
  } else if (tab === 'calendar') {
    actions.prepareOverride(node)
    await actions.loadOverrides(node)
  } else if (tab === 'capabilities') {
    await actions.loadCapabilities(node)
  } else if (tab === 'editor') {
    actions.editNode(node)
  }
}

async function selectNode(node) {
  if (actions.selectNodeContext) actions.selectNodeContext(node || null)
  else currentNodeId.value = node?.id ?? null
  if (!node) return
  await enterTab(workbench.activeTab.value, node)
}

const workbench = useProductionNodeWorkbench({
  nodes: productionNodes,
  selectedNodeId: currentNodeId,
  onEnterTab: enterTab,
  onSelectNode: selectNode,
  onClose: closeWorkbench,
  onDiscard: (tab, node) => actions.rollbackPanel?.(tab, node),
})
const tabs = PRODUCTION_NODE_TABS

const selectedNodeLabel = computed(() => {
  const node = workbench.selectedNode.value
  if (!node) return '未选择'
  return [node.process_name, node.node_code, node.node_name].filter(Boolean).join(' · ')
})
const editorForm = computed(() => (
  canManageNodes.value ? nodeForm.value : (workbench.selectedNode.value || nodeForm.value)
))
const selectedCalendar = computed(() => {
  const calendarId = workbench.selectedNode.value?.calendar_id
  return productionCalendars.value.find(item => String(item.id) === String(calendarId)) || null
})
const finiteMinutes = value => {
  if (value === null || value === undefined || value === '') return null
  const minutes = Number(value)
  return Number.isFinite(minutes) ? minutes : null
}
const selectedNodeCapacityMinutes = computed(() => {
  const nodeMinutes = finiteMinutes(workbench.selectedNode.value?.capacity_minutes)
  if (nodeMinutes !== null) return nodeMinutes
  const calendar = selectedCalendar.value
  const directMinutes = finiteMinutes(calendar?.daily_minutes ?? calendar?.effective_minutes)
  if (directMinutes !== null) return directMinutes
  const shiftMinutes = (calendar?.shifts || []).reduce((total, shift) => {
    const start = Number(shift.start_minute)
    const end = Number(shift.end_minute)
    return total + (Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) : 0)
  }, 0)
  return shiftMinutes || 0
})

function tabId(key) {
  return `production-node-tab-${key}`
}

function panelId(key) {
  return `production-node-panel-${key}`
}

function setTabRef(element, index) {
  if (element) tabRefs.value[index] = element
}

function markPanelDirty(tab, value) {
  if (workbench.activeTab.value === tab) workbench.markDirty(value)
}

function onTabKeydown(event, index) {
  let targetIndex = null
  if (event.key === 'ArrowRight') targetIndex = (index + 1) % tabs.length
  else if (event.key === 'ArrowLeft') targetIndex = (index - 1 + tabs.length) % tabs.length
  else if (event.key === 'Home') targetIndex = 0
  else if (event.key === 'End') targetIndex = tabs.length - 1
  if (targetIndex === null) return
  event.preventDefault()
  const result = workbench.requestTab(tabs[targetIndex].key)
  if (result === false) return
  tabRefs.value[targetIndex]?.focus()
}

function onTabClick(tab, index) {
  const result = workbench.requestTab(tab)
  if (result === false) discardReturnFocus = tabRefs.value[index] || document.activeElement
}

function selectNodeById(value) {
  const node = productionNodes.value.find(item => String(item.id) === String(value))
  workbench.requestNode(node || null)
}

function openCreate() {
  if (!canManageNodes.value) return
  workbench.requestTransition(() => {
    actions.selectNodeContext?.(null)
    currentNodeId.value = null
    actions.resetNodeForm()
    workbench.requestTab('editor')
  })
}

function resetEditor() {
  workbench.requestTransition(() => {
    actions.selectNodeContext?.(null)
    currentNodeId.value = null
    actions.resetNodeForm()
    workbench.markDirty(false)
  })
}

async function handleNodeSaved(result, savedIdentity = {}) {
  const savedId = result?.id ?? result?.node?.id ?? result?.production_node?.id
  let savedNode = null
  if (savedId != null) {
    savedNode = productionNodes.value.find(node => String(node.id) === String(savedId)) || null
  } else if (savedIdentity.id != null) {
    savedNode = productionNodes.value.find(node => String(node.id) === String(savedIdentity.id)) || null
  } else if (savedIdentity.node_code) {
    savedNode = productionNodes.value.find(node => node.node_code === savedIdentity.node_code) || null
  }
  if (!savedNode) return
  actions.selectNodeContext?.(savedNode)
  currentNodeId.value = savedNode.id
  actions.editNode(savedNode)
  workbench.markDirty(false)
  workbench.activeTab.value = 'list'
  await nextTick()
  tabRefs.value[0]?.focus()
}

const focusableSelector = [
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function onDialogKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    if (workbench.showDiscardConfirm.value) {
      cancelDiscard()
      return
    }
    workbench.requestClose()
    return
  }
  if (event.key !== 'Tab') return
  const focusRoot = discardDialogRef.value || dialogRef.value
  const focusable = [...(focusRoot?.querySelectorAll(focusableSelector) || [])]
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable.at(-1)
  const activeElement = document.activeElement
  const activeIndex = focusable.indexOf(activeElement)
  if (event.shiftKey && activeIndex <= 0) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (activeIndex === -1 || activeElement === last)) {
    event.preventDefault()
    first.focus()
  }
}

function acquireBodyScrollLock() {
  if (ownsBodyScrollLock) return
  returnFocus = document.activeElement
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  ownsBodyScrollLock = true
}

function releaseBodyScrollLock() {
  if (!ownsBodyScrollLock) return
  const focusTarget = returnFocus
  document.body.style.overflow = previousBodyOverflow
  ownsBodyScrollLock = false
  previousBodyOverflow = ''
  returnFocus = null
  focusTarget?.focus?.()
}

async function cancelDiscard() {
  const focusTarget = discardReturnFocus
  const restoreTabFocus = focusTarget?.getAttribute?.('role') === 'tab'
  discardReturnFocus = null
  workbench.cancelDiscard()
  await nextTick()
  if (restoreTabFocus) {
    const activeIndex = tabs.findIndex(tab => tab.key === workbench.activeTab.value)
    tabRefs.value[activeIndex]?.focus()
  } else {
    focusTarget?.isConnected && focusTarget.focus()
  }
}

async function confirmDiscard() {
  const focusTarget = discardReturnFocus
  const restoreTabFocus = focusTarget?.getAttribute?.('role') === 'tab'
  discardReturnFocus = null
  const transition = workbench.confirmDiscard()
  await nextTick()
  if (restoreTabFocus) {
    const activeIndex = tabs.findIndex(tab => tab.key === workbench.activeTab.value)
    tabRefs.value[activeIndex]?.focus()
  } else {
    focusTarget?.isConnected && focusTarget.focus()
  }
  await transition
}

watch(workbench.showDiscardConfirm, async visible => {
  if (!visible) return
  if (!discardReturnFocus) discardReturnFocus = document.activeElement
  await nextTick()
  discardDialogRef.value?.querySelector(focusableSelector)?.focus()
})

watch(
  () => props.modelValue,
  async open => {
    if (open) {
      acquireBodyScrollLock()
      if (!workbench.selectedNodeId.value && productionNodes.value.length) {
        workbench.requestNode(productionNodes.value[0])
      }
      await nextTick()
      titleRef.value?.focus()
      return
    }
    discardReturnFocus = null
    releaseBodyScrollLock()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  discardReturnFocus = null
  releaseBodyScrollLock()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="node-workbench-overlay">
      <section
        ref="dialogRef"
        class="node-workbench"
        data-test="production-node-workbench"
        role="dialog"
        aria-modal="true"
        aria-labelledby="production-node-workbench-title"
        @keydown="onDialogKeydown"
      >
        <header class="node-workbench__header">
          <div>
            <h2 id="production-node-workbench-title" ref="titleRef" tabindex="-1">生产节点管理</h2>
            <p>共 {{ productionNodes.length }} 个生产节点</p>
          </div>
          <button
            type="button"
            class="modal-close"
            data-test="workbench-first-focus"
            aria-label="关闭生产节点管理"
            @click="workbench.requestClose"
          >×</button>
        </header>

        <nav class="node-workbench__tabs" role="tablist" aria-label="生产节点管理功能">
          <button
            v-for="(tab, index) in tabs"
            :key="tab.key"
            :ref="element => setTabRef(element, index)"
            :id="tabId(tab.key)"
            type="button"
            role="tab"
            :class="{ 'node-workbench__tab--active': workbench.activeTab.value === tab.key }"
            :aria-selected="workbench.activeTab.value === tab.key"
            :aria-controls="panelId(tab.key)"
            :tabindex="workbench.activeTab.value === tab.key ? 0 : -1"
            @click="onTabClick(tab.key, index)"
            @keydown="onTabKeydown($event, index)"
          >
            {{ tab.label }}
          </button>
        </nav>

        <div class="node-workbench__content">
          <label class="node-workbench__mobile-node-select">
            <span class="sr-only">选择生产节点</span>
            <select
              data-test="mobile-node-select"
              aria-label="选择生产节点"
              :value="workbench.selectedNodeId.value || ''"
              @change="selectNodeById($event.target.value)"
            >
              <option value="">请选择生产节点</option>
              <option v-for="node in productionNodes" :key="node.id" :value="node.id">
                {{ node.process_name }} · {{ node.node_code }} · {{ node.node_name }}
              </option>
            </select>
          </label>

          <NodeListPanel
            :groups="workbench.filteredGroups.value"
            :selected-node-id="workbench.selectedNodeId.value"
            :search="workbench.search.value"
            :status-filter="workbench.statusFilter.value"
            :loading="nodesLoading"
            :error="nodesError"
            :can-create="canManageNodes"
            @update:search="workbench.search.value = $event"
            @update:status-filter="workbench.statusFilter.value = $event"
            @select="workbench.requestNode"
            @retry="actions.loadNodes"
            @create="openCreate"
          />

          <main class="node-workbench__panel">
            <section
              :id="panelId('list')"
              role="tabpanel"
              :aria-labelledby="tabId('list')"
              :hidden="workbench.activeTab.value !== 'list'"
            >
              <section
                v-if="workbench.selectedNode.value"
                class="node-summary"
                data-test="node-summary"
                aria-labelledby="node-summary-title"
              >
                <header class="node-summary__header">
                  <div>
                    <h3 id="node-summary-title">当前节点摘要</h3>
                    <p>
                      {{ workbench.selectedNode.value.node_code }} ·
                      {{ workbench.selectedNode.value.node_name }}
                    </p>
                  </div>
                  <span>{{ workbench.selectedNode.value.process_name || '未命名工序' }}</span>
                </header>
                <div v-if="nodeSummaryError" class="node-summary__notice node-summary__notice--error" role="alert">
                  <span>{{ nodeSummaryError }}</span>
                  <button
                    type="button"
                    class="btn btn-default"
                    :disabled="nodeSummaryLoading"
                    @click="actions.loadNodeSummary?.(workbench.selectedNode.value)"
                  >重试</button>
                </div>
                <div v-else-if="nodeSummaryLoading" class="node-summary__notice" role="status">
                  正在加载节点摘要…
                </div>
                <dl class="node-summary__grid">
                  <div><dt>日容量</dt><dd>{{ selectedNodeCapacityMinutes }} 分钟</dd></div>
                  <div><dt>能力限制</dt><dd>{{ nodeSummary.capability_count || 0 }} 条</dd></div>
                  <div><dt>未来日历例外</dt><dd>{{ nodeSummary.future_override_count || 0 }} 条</dd></div>
                  <div><dt>容量模式</dt><dd>{{ workbench.selectedNode.value.capacity_mode === 'batch' ? '批处理产能' : '独占产能' }}</dd></div>
                </dl>
              </section>
              <div v-else class="node-workbench__empty">请选择生产节点查看摘要</div>
              <slot
                :active-tab="workbench.activeTab.value"
                :selected-node="workbench.selectedNode.value"
                :mark-dirty="workbench.markDirty"
                :production-calendars="productionCalendars"
                :process-options="processOptions"
                :permissions="permissions"
              />
            </section>

            <section
              :id="panelId('editor')"
              role="tabpanel"
              :aria-labelledby="tabId('editor')"
              :hidden="workbench.activeTab.value !== 'editor'"
            >
              <NodeEditorPanel
                v-if="canManageNodes || workbench.selectedNode.value"
                :form="editorForm"
                :process-options="processOptions"
                :calendars="productionCalendars"
                :calendar-loading="calendarsLoading"
                :calendar-error="calendarsError"
                :on-retry-calendars="actions.loadNodes"
                :can-manage="canManageNodes"
                :saving="nodeSaving"
                :on-reset="resetEditor"
                :on-save="actions.saveNode"
                @dirty-change="markPanelDirty('editor', $event)"
                @saved="handleNodeSaved"
              />
              <div v-else class="node-workbench__empty">请选择生产节点查看节点资料</div>
            </section>

            <section
              :id="panelId('calendar')"
              role="tabpanel"
              :aria-labelledby="tabId('calendar')"
              :hidden="workbench.activeTab.value !== 'calendar'"
            >
              <NodeCalendarPanel
                :node="workbench.selectedNode.value"
                :calendar="selectedCalendar"
                :calendar-loading="calendarsLoading"
                :calendar-error="calendarsError"
                :overrides="nodeOverrides"
                :form="overrideForm"
                :loading="overridesLoading"
                :error="overridesError"
                :saving="overrideSaving"
                :can-manage="canManageCalendars && Boolean(workbench.selectedNode.value)"
                :on-retry="() => actions.loadOverrides(workbench.selectedNode.value)"
                :on-retry-calendar="actions.loadNodes"
                :on-save="actions.createCalendarOverride"
                :on-cancel-override="actions.cancelOverride"
                @dirty-change="markPanelDirty('calendar', $event)"
                @saved="markPanelDirty('calendar', false)"
              />
            </section>

            <section
              :id="panelId('capabilities')"
              role="tabpanel"
              :aria-labelledby="tabId('capabilities')"
              :hidden="workbench.activeTab.value !== 'capabilities'"
            >
              <NodeCapabilityPanel
                :node="workbench.selectedNode.value"
                :form="capabilityForm"
                :loading="capabilitiesLoading"
                :error="capabilitiesError"
                :saving="capabilitySaving"
                :can-manage="canManageCapabilities && Boolean(workbench.selectedNode.value)"
                :on-add="actions.addCapability"
                :on-remove="actions.removeCapability"
                :on-save="actions.saveCapabilities"
                :on-retry="() => actions.loadCapabilities(workbench.selectedNode.value)"
                @dirty-change="markPanelDirty('capabilities', $event)"
                @saved="markPanelDirty('capabilities', false)"
              />
            </section>
          </main>
        </div>

        <footer class="node-workbench__footer">
          <span>当前节点：{{ selectedNodeLabel }}</span>
          <button
            type="button"
            class="btn btn-default"
            data-test="workbench-last-focus"
            @click="workbench.requestClose"
          >关闭</button>
        </footer>

        <div
          v-if="workbench.showDiscardConfirm.value"
          ref="discardDialogRef"
          class="node-discard-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-label="未保存更改"
        >
          <p>当前页签存在未保存更改，是否放弃？</p>
          <div>
            <button type="button" class="btn btn-default" @click="cancelDiscard">继续编辑</button>
            <button type="button" class="btn btn-danger" @click="confirmDiscard">放弃更改</button>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.node-workbench-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgb(15 23 42 / 55%);
}

.node-workbench {
  position: relative;
  width: min(1400px, 96vw);
  height: calc(100dvh - 32px);
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  overflow: hidden;
  background: var(--bg-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
}

.node-workbench__header,
.node-workbench__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-light);
}

.node-workbench__header h2,
.node-workbench__header p {
  margin: 0;
}

.node-workbench__header h2 {
  font-size: 20px;
}

.node-workbench__header p,
.node-workbench__footer span {
  margin-top: 3px;
  color: var(--text-placeholder);
  font-size: 12px;
}

.node-workbench__tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-light);
}

.node-workbench__tabs button {
  flex: 0 0 auto;
  min-height: 42px;
  padding: 8px 14px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.node-workbench__tabs .node-workbench__tab--active {
  border-bottom-color: var(--primary);
  color: var(--primary);
  font-weight: 600;
}

.node-workbench__content {
  min-height: 0;
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
}

.node-workbench__panel {
  min-height: 0;
  overflow: auto;
  padding: 20px;
}

.node-summary {
  max-width: 980px;
  margin: 0 auto;
}

.node-summary__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.node-summary__header h3,
.node-summary__header p {
  margin: 0;
}

.node-summary__header p {
  margin-top: 6px;
  color: var(--text-secondary);
}

.node-summary__header > span {
  color: var(--text-placeholder);
  font-size: 13px;
}

.node-summary__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 0;
}

.node-summary__grid div {
  padding: 16px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}

.node-summary__grid dt {
  color: var(--text-placeholder);
  font-size: 12px;
}

.node-summary__grid dd {
  margin: 6px 0 0;
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 600;
}

.node-summary__notice,
.node-workbench__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 96px;
  color: var(--text-placeholder);
  text-align: center;
}

.node-summary__notice--error {
  color: var(--danger);
}

.node-workbench__mobile-node-select {
  display: none;
}

.node-workbench__footer {
  border-top: 1px solid var(--border-light);
  border-bottom: 0;
}

.node-discard-dialog {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  place-content: center;
  padding: 20px;
  background: rgb(15 23 42 / 45%);
  text-align: center;
}

.node-discard-dialog p,
.node-discard-dialog > div {
  width: min(420px, calc(100vw - 48px));
  margin: 0;
  padding: 20px 24px 12px;
  background: var(--bg-surface);
}

.node-discard-dialog p {
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  font-weight: 600;
}

.node-discard-dialog > div {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 0;
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 899px) {
  .node-workbench-overlay {
    padding: 0;
  }

  .node-workbench {
    width: 100vw;
    height: 100dvh;
    border-radius: 0;
  }

  .node-workbench__content {
    display: block;
    overflow: auto;
  }

  .node-list-panel {
    display: none;
  }

  .node-workbench__mobile-node-select {
    display: block;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border-light);
  }

  .node-workbench__mobile-node-select select {
    width: 100%;
    min-height: 38px;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg-surface);
  }

  .node-workbench__panel {
    overflow: visible;
    padding: 16px;
  }

  .node-summary__header {
    display: block;
  }

  .node-summary__header > span {
    display: block;
    margin-top: 8px;
  }

  .node-summary__grid {
    grid-template-columns: 1fr;
  }
}
</style>
