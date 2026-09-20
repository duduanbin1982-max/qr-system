<script setup>
import { computed, nextTick, onBeforeUnmount, ref, unref, watch } from 'vue'

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
let returnFocus = null
let previousBodyOverflow = ''
let ownsBodyScrollLock = false
let discardReturnFocus = null

const state = props.manager.state
const actions = props.manager.actions
const permissions = props.manager.permissions
const productionNodes = computed(() => unref(state.productionNodes) || [])
const productionCalendars = computed(() => unref(state.productionCalendars) || [])
const nodesLoading = computed(() => Boolean(unref(state.nodesLoading)))
const nodesError = computed(() => String(unref(state.nodesError) || ''))
const nodeForm = computed(() => unref(state.nodeForm) || {})
const nodeSaving = computed(() => Boolean(unref(state.nodeSaving)))
const canManageNodes = computed(() => Boolean(unref(permissions.canManageNodes)))

function closeWorkbench() {
  emit('update:modelValue', false)
  emit('closed')
}

async function enterTab(tab, node) {
  if (!node) return
  if (tab === 'calendar') {
    actions.prepareOverride(node)
    await actions.loadOverrides(node)
  } else if (tab === 'capabilities') {
    await actions.loadCapabilities(node)
  } else if (tab === 'editor') {
    actions.editNode(node)
  }
}

async function selectNode(node) {
  await enterTab(workbench.activeTab.value, node)
}

const workbench = useProductionNodeWorkbench({
  nodes: productionNodes,
  onEnterTab: enterTab,
  onSelectNode: selectNode,
  onClose: closeWorkbench,
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

function selectNodeById(value) {
  const node = productionNodes.value.find(item => String(item.id) === String(value))
  workbench.requestNode(node || null)
}

function openCreate() {
  if (!canManageNodes.value) return
  workbench.requestTransition(() => {
    actions.resetNodeForm()
    workbench.selectedNodeId.value = null
    workbench.requestTab('editor')
  })
}

function resetEditor() {
  workbench.requestTransition(() => {
    actions.resetNodeForm()
    workbench.selectedNodeId.value = null
    workbench.markDirty(false)
  })
}

async function handleNodeSaved(result) {
  await actions.loadNodes()
  const savedId = result?.id ?? result?.node?.id ?? result?.production_node?.id
  const savedNode = productionNodes.value.find(node => String(node.id) === String(savedId))
  if (savedNode) await workbench.requestNode(savedNode)
  workbench.markDirty(false)
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
  discardReturnFocus = null
  workbench.cancelDiscard()
  await nextTick()
  focusTarget?.isConnected && focusTarget.focus()
}

async function confirmDiscard() {
  const focusTarget = discardReturnFocus
  discardReturnFocus = null
  workbench.confirmDiscard()
  await nextTick()
  focusTarget?.isConnected && focusTarget.focus()
}

watch(workbench.showDiscardConfirm, async visible => {
  if (!visible) return
  discardReturnFocus = document.activeElement
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
          <button type="button" class="modal-close" aria-label="关闭生产节点管理" @click="workbench.requestClose">×</button>
        </header>

        <nav class="node-workbench__tabs" role="tablist" aria-label="生产节点管理功能">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            role="tab"
            :class="{ 'node-workbench__tab--active': workbench.activeTab.value === tab.key }"
            :aria-selected="workbench.activeTab.value === tab.key"
            @click="workbench.requestTab(tab.key)"
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
            <NodeEditorPanel
              v-if="workbench.activeTab.value === 'editor'"
              :form="editorForm"
              :process-options="processOptions"
              :calendars="productionCalendars"
              :can-manage="canManageNodes"
              :saving="nodeSaving"
              :on-reset="resetEditor"
              :on-save="actions.saveNode"
              @dirty-change="workbench.markDirty"
              @saved="handleNodeSaved"
            />
            <slot
              v-else
              :active-tab="workbench.activeTab.value"
              :selected-node="workbench.selectedNode.value"
              :mark-dirty="workbench.markDirty"
              :production-calendars="productionCalendars"
              :process-options="processOptions"
              :permissions="permissions"
            />
          </main>
        </div>

        <footer class="node-workbench__footer">
          <span>当前节点：{{ selectedNodeLabel }}</span>
          <button type="button" class="btn btn-default" @click="workbench.requestClose">关闭</button>
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
  padding: 0 16px;
  border-bottom: 1px solid var(--border-light);
}

.node-workbench__tabs button {
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
}
</style>
