# Production Node Management Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Replace the long production-node modal inside the scheduling page with a viewport-fixed, responsive, accessible workbench whose node list, editor, calendar, and capability panels are independently scrollable and saveable.

**Architecture:** Keep useProductionNodes.js as the single owner of production-node data and API commands. Add a small workbench UI-state composable plus five focused Vue components, mount the workbench through Teleport, and leave GanttChart.vue responsible only for opening the workbench and consuming shared node data.

**Tech Stack:** Vue 3.5 Composition API, Vue Test Utils, Vitest 4, Playwright 1.62, existing API facade and CSS variables.

## Global Constraints

- The workbench is frontend-only; do not modify backend APIs, database schema, migrations, permission codes, idempotency semantics, or audit semantics.
- Desktop breakpoint is 900px.
- At 1366×768 the title, tabs, and footer must remain visible.
- The workbench must be positioned relative to the viewport through Teleport to body.
- Clicking the overlay must not close the workbench.
- Node list, editor, calendar, and capability panels share one selected production node.
- Each panel saves independently; do not introduce a global “save all” action.
- Unsaved changes must guard node changes, tab changes, Escape, and close actions.
- Existing automatic scheduling, dynamic replanning, downtime management, and schedule adjustment behavior must remain unchanged.
- All changes use TDD and each task ends with an independent commit.

---

## File Structure

### New production files

- frontend/src/components/production-nodes/ProductionNodeWorkbench.vue  
  Owns Teleport, responsive shell, tabs, focus management, background scroll lock, and discard confirmation.
- frontend/src/components/production-nodes/NodeListPanel.vue  
  Owns node search, status filters, process grouping, selection, and summary display.
- frontend/src/components/production-nodes/NodeEditorPanel.vue  
  Owns create/edit form rendering and dirty-state emission.
- frontend/src/components/production-nodes/NodeCalendarPanel.vue  
  Owns base-calendar summary, override list, override creation, cancellation, and tab-local errors.
- frontend/src/components/production-nodes/NodeCapabilityPanel.vue  
  Owns capability rows, batch-only fields, add/remove controls, and save form.
- frontend/src/composables/gantt/useProductionNodeWorkbench.js  
  Owns active tab, selected node, search/filter state, dirty-transition guard, and pending transition confirmation.

### Modified production files

- frontend/src/composables/gantt/useProductionNodes.js  
  Adds tab-local loading/error state, calendar-override list/cancel commands, stale-request guards, and a grouped manager facade.
- frontend/src/composables/useGantt.js  
  Exposes the grouped production-node manager while preserving the flat values used by capacity scheduling.
- frontend/src/views/GanttChart.vue:281-381  
  Replaces the inline production-node modal with ProductionNodeWorkbench.

### New and modified tests

- frontend/tests/unit/useProductionNodeWorkbench.spec.js
- frontend/tests/unit/ProductionNodeWorkbench.spec.js
- frontend/tests/unit/ProductionNodePanels.spec.js
- frontend/tests/unit/useProductionNodes.spec.js
- frontend/tests/unit/GanttChartProductionNodes.spec.js
- frontend/tests/e2e/production-node-workbench.spec.js

---

### Task 1: Harden the production-node data controller

**Files:**
- Modify: frontend/src/composables/gantt/useProductionNodes.js
- Modify: frontend/tests/unit/useProductionNodes.spec.js

**Interfaces:**
- Consumes: existing production API facade methods listProductionNodes, listScheduleCalendars, listProductionNodeCapabilities, replaceProductionNodeCapabilities, listProductionNodeOverrides, createProductionNodeOverride, and cancelProductionNodeOverride.
- Produces: nodeManager with state, permissions, and actions groups; loadOverrides(node); cancelOverride(override); panel-local error and saving refs.

- [ ] **Step 1: Write failing tests for tab-local errors, override loading, cancellation, and stale request protection**

Add API mocks:

~~~javascript
const mocks = vi.hoisted(() => ({
  listProductionNodes: vi.fn(),
  listScheduleCalendars: vi.fn(),
  createProductionNode: vi.fn(),
  updateProductionNode: vi.fn(),
  listProductionNodeCapabilities: vi.fn(),
  replaceProductionNodeCapabilities: vi.fn(),
  listProductionNodeOverrides: vi.fn(),
  createProductionNodeOverride: vi.fn(),
  cancelProductionNodeOverride: vi.fn(),
}))
~~~

Expose the new mocks through the existing API mock:

~~~javascript
vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      production: {
        listProductionNodes: mocks.listProductionNodes,
        listScheduleCalendars: mocks.listScheduleCalendars,
        createProductionNode: mocks.createProductionNode,
        updateProductionNode: mocks.updateProductionNode,
        listProductionNodeCapabilities: mocks.listProductionNodeCapabilities,
        replaceProductionNodeCapabilities: mocks.replaceProductionNodeCapabilities,
        listProductionNodeOverrides: mocks.listProductionNodeOverrides,
        createProductionNodeOverride: mocks.createProductionNodeOverride,
        cancelProductionNodeOverride: mocks.cancelProductionNodeOverride,
      },
    },
  },
}))
~~~

Add focused tests:

~~~javascript
it('keeps node load errors in node state and allows retry', async () => {
  mocks.listProductionNodes
    .mockRejectedValueOnce(new Error('节点目录不可用'))
    .mockResolvedValueOnce({ nodes: [] })
  const nodes = createNodes()

  await nodes.loadNodes()
  expect(nodes.nodesError.value).toBe('节点目录不可用')

  await nodes.loadNodes()
  expect(nodes.nodesError.value).toBe('')
})

it('loads and cancels calendar overrides for the selected node', async () => {
  mocks.listProductionNodeOverrides.mockResolvedValue({
    overrides: [{ id: 81, production_node_id: 11, status: 'active' }],
  })
  mocks.cancelProductionNodeOverride.mockResolvedValue({ id: 81, status: 'cancelled' })
  const nodes = createNodes()

  await nodes.loadOverrides({ id: 11 })
  expect(nodes.nodeOverrides.value).toEqual([
    expect.objectContaining({ id: 81, production_node_id: 11 }),
  ])

  await nodes.cancelOverride({ id: 81, production_node_id: 11 })
  expect(mocks.cancelProductionNodeOverride).toHaveBeenCalledWith(
    81,
    expect.objectContaining({ reason: expect.any(String), idempotency_key: expect.any(String) }),
  )
})

it('ignores a stale capability response after the selected node changes', async () => {
  let resolveFirst
  mocks.listProductionNodeCapabilities
    .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
    .mockResolvedValueOnce({ capabilities: [{ product_family: 'CURRENT' }] })
  const nodes = createNodes()

  const first = nodes.loadCapabilities({ id: 11, node_code: 'A' })
  await nodes.loadCapabilities({ id: 12, node_code: 'B' })
  resolveFirst({ capabilities: [{ product_family: 'STALE' }] })
  await first

  expect(nodes.capabilityForm.value.production_node_id).toBe(12)
  expect(nodes.capabilityForm.value.capabilities[0].product_family).toBe('CURRENT')
})

it('ignores stale calendar overrides after the selected node changes', async () => {
  let resolveFirst
  mocks.listProductionNodeOverrides
    .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
    .mockResolvedValueOnce({ overrides: [{ id: 82, production_node_id: 12 }] })
  const nodes = createNodes()

  const first = nodes.loadOverrides({ id: 11 })
  await nodes.loadOverrides({ id: 12 })
  resolveFirst({ overrides: [{ id: 81, production_node_id: 11 }] })
  await first

  expect(nodes.nodeOverrides.value).toEqual([
    expect.objectContaining({ id: 82, production_node_id: 12 }),
  ])
})
~~~

- [ ] **Step 2: Run the controller tests and verify RED**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/useProductionNodes.spec.js
~~~

Expected: FAIL because nodesError, nodeOverrides, loadOverrides, cancelOverride, and request sequencing do not exist.

- [ ] **Step 3: Implement panel-local state and request sequencing**

Add refs near the existing state:

~~~javascript
const nodesError = ref('')
const nodeSaving = ref(false)
const capabilitiesError = ref('')
const capabilitySaving = ref(false)
const nodeOverrides = ref([])
const overridesLoading = ref(false)
const overridesError = ref('')
const overrideSaving = ref(false)
let capabilityRequest = 0
let overrideRequest = 0
~~~

Update loadNodes so it preserves an inline error:

~~~javascript
async function loadNodes(params = {}) {
  nodesLoading.value = true
  nodesError.value = ''
  try {
    const [data, calendarData] = await Promise.all([
      api.domains.production.listProductionNodes({ limit: 500, ...params }),
      api.domains.production.listScheduleCalendars(),
    ])
    productionNodes.value = data.nodes || data || []
    productionCalendars.value = calendarData.calendars || calendarData || []
  } catch (error) {
    nodesError.value = error.message || '加载生产节点失败'
    showToast(nodesError.value, 'error')
  } finally {
    nodesLoading.value = false
  }
}
~~~

Guard capability responses:

~~~javascript
async function loadCapabilities(node) {
  if (!canManageCapabilities.value || !node?.id) return null
  const requestId = ++capabilityRequest
  capabilitiesLoading.value = true
  capabilitiesError.value = ''
  try {
    const result = await api.domains.production.listProductionNodeCapabilities(node.id)
    if (requestId !== capabilityRequest) return null
    capabilityForm.value = capabilityFormFrom(node, result.capabilities || [])
    return result
  } catch (error) {
    if (requestId === capabilityRequest) {
      capabilitiesError.value = error.message || '加载节点能力失败'
      showToast(capabilitiesError.value, 'error')
    }
    return null
  } finally {
    if (requestId === capabilityRequest) capabilitiesLoading.value = false
  }
}
~~~

Add override commands:

~~~javascript
async function loadOverrides(node) {
  if (!canManageCalendars.value || !node?.id) return null
  const requestId = ++overrideRequest
  overridesLoading.value = true
  overridesError.value = ''
  try {
    const result = await api.domains.production.listProductionNodeOverrides(
      node.id,
      { limit: 200 },
    )
    if (requestId !== overrideRequest) return null
    nodeOverrides.value = result.overrides || result.items || []
    return result
  } catch (error) {
    if (requestId === overrideRequest) {
      overridesError.value = error.message || '加载节点日历例外失败'
      showToast(overridesError.value, 'error')
    }
    return null
  } finally {
    if (requestId === overrideRequest) overridesLoading.value = false
  }
}

async function cancelOverride(override, reason = '取消节点日历例外') {
  if (!canManageCalendars.value || !override?.id) return null
  overrideSaving.value = true
  try {
    const result = await api.domains.production.cancelProductionNodeOverride(
      override.id,
      {
        reason,
        idempotency_key: commandKey('production-node-calendar-cancel', override.id),
      },
    )
    const node = productionNodes.value.find(
      item => String(item.id) === String(override.production_node_id),
    )
    if (node) await loadOverrides(node)
    return result
  } finally {
    overrideSaving.value = false
  }
}
~~~

Rename the current write functions without changing their existing validation, payload, toast, or API bodies:

- saveNode becomes saveNodeCommand.
- createCalendarOverride becomes createCalendarOverrideCommand.
- saveCapabilities becomes saveCapabilitiesCommand.

Then expose these exact guarded wrappers:

~~~javascript
async function saveNode() {
  if (!canManageNodes.value || nodeSaving.value) return null
  nodeSaving.value = true
  try {
    return await saveNodeCommand()
  } finally {
    nodeSaving.value = false
  }
}

async function createCalendarOverride() {
  if (!canManageCalendars.value || overrideSaving.value) return null
  overrideSaving.value = true
  try {
    return await createCalendarOverrideCommand()
  } finally {
    overrideSaving.value = false
  }
}

async function saveCapabilities() {
  if (!canManageCapabilities.value || capabilitySaving.value) return null
  capabilitySaving.value = true
  try {
    return await saveCapabilitiesCommand()
  } finally {
    capabilitySaving.value = false
  }
}
~~~

Expose a grouped facade without duplicating refs:

~~~javascript
const nodeManager = {
  state: {
    productionNodes,
    productionCalendars,
    nodesByProcess,
    nodesLoading,
    nodesError,
    nodeForm,
    nodeSaving,
    overrideForm,
    nodeOverrides,
    overridesLoading,
    overridesError,
    overrideSaving,
    capabilityForm,
    capabilitiesLoading,
    capabilitiesError,
    capabilitySaving,
  },
  permissions: {
    canManageNodes,
    canManageCapabilities,
    canManageCalendars,
  },
  actions: {
    loadNodes,
    resetNodeForm,
    editNode,
    saveNode,
    prepareOverride,
    loadOverrides,
    createCalendarOverride,
    cancelOverride,
    loadCapabilities,
    addCapability,
    removeCapability,
    saveCapabilities,
  },
}
~~~

- [ ] **Step 4: Run the controller tests and verify GREEN**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/useProductionNodes.spec.js
~~~

Expected: all useProductionNodes tests PASS.

- [ ] **Step 5: Commit**

~~~bash
git add frontend/src/composables/gantt/useProductionNodes.js frontend/tests/unit/useProductionNodes.spec.js
git commit -m "refactor: expose production node workbench manager"
~~~

---

### Task 2: Implement the workbench UI state machine

**Files:**
- Create: frontend/src/composables/gantt/useProductionNodeWorkbench.js
- Create: frontend/tests/unit/useProductionNodeWorkbench.spec.js

**Interfaces:**
- Consumes: computed nodes array and callbacks onSelectNode, onEnterTab, and onClose.
- Produces: activeTab, selectedNodeId, search, statusFilter, filteredGroups, isDirty, discard confirmation state, requestTab, requestNode, requestClose, confirmDiscard, cancelDiscard, and markDirty.

- [ ] **Step 1: Write failing state-machine tests**

~~~javascript
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useProductionNodeWorkbench } from '@/composables/gantt/useProductionNodeWorkbench.js'

function createWorkbench() {
  return useProductionNodeWorkbench({
    nodes: ref([
      { id: 11, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01', status: 'active' },
      { id: 12, process_id: 7, process_name: '焊接', node_code: 'WELD-02', node_name: '焊接-02', status: 'maintenance' },
    ]),
    onEnterTab: vi.fn(),
    onSelectNode: vi.fn(),
    onClose: vi.fn(),
  })
}

describe('useProductionNodeWorkbench', () => {
  it('filters nodes by query and status without changing the selected node', () => {
    const workbench = createWorkbench()
    workbench.selectedNodeId.value = 11
    workbench.search.value = '02'
    workbench.statusFilter.value = 'maintenance'

    expect(workbench.filteredGroups.value[0].nodes.map(node => node.id)).toEqual([12])
    expect(workbench.selectedNodeId.value).toBe(11)
  })

  it('guards tab, node, and close transitions while dirty', () => {
    const workbench = createWorkbench()
    workbench.markDirty(true)

    expect(workbench.requestTab('calendar')).toBe(false)
    expect(workbench.showDiscardConfirm.value).toBe(true)

    workbench.confirmDiscard()
    expect(workbench.activeTab.value).toBe('calendar')
    expect(workbench.isDirty.value).toBe(false)
  })
})
~~~

- [ ] **Step 2: Run the new tests and verify RED**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/useProductionNodeWorkbench.spec.js
~~~

Expected: FAIL because useProductionNodeWorkbench.js does not exist.

- [ ] **Step 3: Implement the state machine**

~~~javascript
import { computed, ref } from 'vue'

export const PRODUCTION_NODE_TABS = Object.freeze([
  { key: 'list', label: '节点列表' },
  { key: 'editor', label: '节点编辑' },
  { key: 'calendar', label: '工作日历' },
  { key: 'capabilities', label: '能力限制' },
])

export function useProductionNodeWorkbench({
  nodes,
  onEnterTab = () => {},
  onSelectNode = () => {},
  onClose = () => {},
}) {
  const activeTab = ref('list')
  const selectedNodeId = ref(null)
  const search = ref('')
  const statusFilter = ref('')
  const isDirty = ref(false)
  const showDiscardConfirm = ref(false)
  const pendingTransition = ref(null)

  const selectedNode = computed(() => (
    nodes.value.find(node => String(node.id) === String(selectedNodeId.value)) || null
  ))

  const filteredGroups = computed(() => {
    const query = search.value.trim().toLocaleLowerCase()
    const groups = new Map()
    for (const node of nodes.value) {
      if (statusFilter.value && node.status !== statusFilter.value) continue
      const haystack = [node.node_code, node.node_name, node.process_name]
        .filter(Boolean).join(' ').toLocaleLowerCase()
      if (query && !haystack.includes(query)) continue
      const key = String(node.process_id)
      if (!groups.has(key)) {
        groups.set(key, {
          process_id: node.process_id,
          process_name: node.process_name || '未命名工序',
          nodes: [],
        })
      }
      groups.get(key).nodes.push(node)
    }
    return [...groups.values()]
  })

  function runOrGuard(transition) {
    if (!isDirty.value) {
      transition()
      return true
    }
    pendingTransition.value = transition
    showDiscardConfirm.value = true
    return false
  }

  function requestTab(tab) {
    return runOrGuard(() => {
      activeTab.value = tab
      onEnterTab(tab, selectedNode.value)
    })
  }

  function requestNode(node) {
    return runOrGuard(() => {
      selectedNodeId.value = node?.id ?? null
      onSelectNode(node || null)
    })
  }

  function requestClose() {
    return runOrGuard(() => onClose())
  }

  function confirmDiscard() {
    isDirty.value = false
    showDiscardConfirm.value = false
    const transition = pendingTransition.value
    pendingTransition.value = null
    transition?.()
  }

  function cancelDiscard() {
    showDiscardConfirm.value = false
    pendingTransition.value = null
  }

  function markDirty(value = true) {
    isDirty.value = Boolean(value)
  }

  return {
    activeTab,
    selectedNodeId,
    selectedNode,
    search,
    statusFilter,
    filteredGroups,
    isDirty,
    showDiscardConfirm,
    requestTab,
    requestNode,
    requestClose,
    confirmDiscard,
    cancelDiscard,
    markDirty,
  }
}
~~~

- [ ] **Step 4: Run state-machine tests and verify GREEN**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/useProductionNodeWorkbench.spec.js
~~~

Expected: all workbench state tests PASS.

- [ ] **Step 5: Commit**

~~~bash
git add frontend/src/composables/gantt/useProductionNodeWorkbench.js frontend/tests/unit/useProductionNodeWorkbench.spec.js
git commit -m "feat: add production node workbench state machine"
~~~

---

### Task 3: Build the workbench shell and node list panel

**Files:**
- Create: frontend/src/components/production-nodes/ProductionNodeWorkbench.vue
- Create: frontend/src/components/production-nodes/NodeListPanel.vue
- Create: frontend/tests/unit/ProductionNodeWorkbench.spec.js

**Interfaces:**
- Consumes: manager facade from Task 1, processOptions array, and modelValue boolean.
- Produces: update:modelValue and closed events plus a viewport-fixed dialog with selectable nodes.

- [ ] **Step 1: Write failing shell tests**

Create a manager fixture that uses real refs:

~~~javascript
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProductionNodeWorkbench from '@/components/production-nodes/ProductionNodeWorkbench.vue'

function managerFixture() {
  const nodes = ref([
    { id: 11, process_id: 7, process_name: '焊接', node_code: 'WELD-01', node_name: '焊接-01', status: 'active', capacity_mode: 'exclusive' },
  ])
  return {
    state: {
      productionNodes: nodes,
      productionCalendars: ref([]),
      nodesLoading: ref(false),
      nodesError: ref(''),
      nodeForm: ref({}),
      nodeSaving: ref(false),
      overrideForm: ref({}),
      nodeOverrides: ref([]),
      overridesLoading: ref(false),
      overridesError: ref(''),
      overrideSaving: ref(false),
      capabilityForm: ref({ capabilities: [] }),
      capabilitiesLoading: ref(false),
      capabilitiesError: ref(''),
      capabilitySaving: ref(false),
    },
    permissions: {
      canManageNodes: ref(true),
      canManageCapabilities: ref(true),
      canManageCalendars: ref(true),
    },
    actions: {
      loadNodes: vi.fn(),
      resetNodeForm: vi.fn(),
      editNode: vi.fn(),
      saveNode: vi.fn(),
      prepareOverride: vi.fn(),
      loadOverrides: vi.fn(),
      createCalendarOverride: vi.fn(),
      cancelOverride: vi.fn(),
      loadCapabilities: vi.fn(),
      addCapability: vi.fn(),
      removeCapability: vi.fn(),
      saveCapabilities: vi.fn(),
    },
  }
}

afterEach(() => {
  document.body.innerHTML = ''
  document.body.style.overflow = ''
})

it('teleports a labelled modal workbench to body and does not close on overlay click', async () => {
  const wrapper = mount(ProductionNodeWorkbench, {
    props: { modelValue: true, manager: managerFixture(), processOptions: [] },
    attachTo: document.body,
  })
  const dialog = document.body.querySelector('[role="dialog"]')

  expect(dialog).not.toBeNull()
  expect(dialog.getAttribute('aria-modal')).toBe('true')
  expect(document.body.style.overflow).toBe('hidden')

  await document.body.querySelector('.node-workbench-overlay').click()
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
})
~~~

- [ ] **Step 2: Run shell tests and verify RED**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/ProductionNodeWorkbench.spec.js
~~~

Expected: FAIL because the workbench and list components do not exist.

- [ ] **Step 3: Implement NodeListPanel**

Use explicit props and events:

~~~vue
<script setup>
defineProps({
  groups: { type: Array, default: () => [] },
  selectedNodeId: { type: [Number, String], default: null },
  search: { type: String, default: '' },
  statusFilter: { type: String, default: '' },
  loading: Boolean,
  error: { type: String, default: '' },
})
defineEmits([
  'update:search',
  'update:statusFilter',
  'select',
  'retry',
  'create',
])
</script>
~~~

The template must render data-test attributes node-search, node-status-filter, and node-item-ID so unit and browser tests have stable selectors.

- [ ] **Step 4: Implement ProductionNodeWorkbench shell**

Define and unwrap the manager contract without creating a second controller instance:

~~~javascript
import { computed, nextTick, onBeforeUnmount, ref, unref, watch } from 'vue'

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
let returnFocus = null
let previousBodyOverflow = ''

const state = props.manager.state
const actions = props.manager.actions
const permissions = props.manager.permissions
const productionNodes = computed(() => unref(state.productionNodes) || [])
const productionCalendars = computed(() => unref(state.productionCalendars) || [])
const nodesLoading = computed(() => Boolean(unref(state.nodesLoading)))
const nodesError = computed(() => String(unref(state.nodesError) || ''))

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

function selectNodeById(value) {
  const node = productionNodes.value.find(item => String(item.id) === String(value))
  workbench.requestNode(node || null)
}

function openCreate() {
  actions.resetNodeForm()
  workbench.selectedNodeId.value = null
  workbench.markDirty(false)
  workbench.requestTab('editor')
}
~~~

The top-level template must use Teleport:

~~~vue
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
            :aria-selected="workbench.activeTab.value === tab.key"
            @click="workbench.requestTab(tab.key)"
          >{{ tab.label }}</button>
        </nav>

        <div class="node-workbench__content">
          <label class="node-workbench__mobile-node-select">
            <span class="sr-only">选择生产节点</span>
            <select
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
            @select="workbench.requestNode"
            @retry="actions.loadNodes"
            @create="openCreate"
          />
          <main class="node-workbench__panel">
            <slot :active-tab="workbench.activeTab.value" :selected-node="workbench.selectedNode.value" />
          </main>
        </div>

        <footer class="node-workbench__footer">
          <span>当前节点：{{ selectedNodeLabel }}</span>
          <button type="button" class="btn btn-default" @click="workbench.requestClose">关闭</button>
        </footer>
        <div v-if="workbench.showDiscardConfirm.value" class="node-discard-dialog" role="alertdialog" aria-modal="true" aria-label="未保存更改">
          <p>当前页签存在未保存更改，是否放弃？</p>
          <div>
            <button type="button" class="btn btn-default" @click="workbench.cancelDiscard">继续编辑</button>
            <button type="button" class="btn btn-danger" @click="workbench.confirmDiscard">放弃更改</button>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>
~~~

Implement body scroll lock, initial node selection, focus trap, and focus return:

~~~javascript
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
  const focusable = [...dialogRef.value.querySelectorAll(focusableSelector)]
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(
  () => props.modelValue,
  async open => {
    if (open) {
      returnFocus = document.activeElement
      previousBodyOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      if (!workbench.selectedNodeId.value && productionNodes.value.length) {
        workbench.requestNode(productionNodes.value[0])
      }
      await nextTick()
      titleRef.value?.focus()
      return
    }
    document.body.style.overflow = previousBodyOverflow
    returnFocus?.focus?.()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow
  returnFocus?.focus?.()
})
~~~

- [ ] **Step 5: Add responsive shell CSS**

Use scoped CSS with these fixed constraints:

~~~css
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
  width: min(1400px, 96vw);
  height: calc(100dvh - 32px);
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  overflow: hidden;
  background: var(--bg-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
}
.node-workbench__content {
  min-height: 0;
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
}
.node-workbench__panel,
.node-list-panel__scroll {
  min-height: 0;
  overflow: auto;
}
.node-workbench__mobile-node-select { display: none; }
@media (max-width: 899px) {
  .node-workbench-overlay { padding: 0; }
  .node-workbench { width: 100vw; height: 100dvh; border-radius: 0; }
  .node-workbench__content { display: block; }
  .node-list-panel { display: none; }
  .node-workbench__mobile-node-select { display: block; }
}
~~~

- [ ] **Step 6: Run shell tests and verify GREEN**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/ProductionNodeWorkbench.spec.js
~~~

Expected: workbench shell and node-list tests PASS.

- [ ] **Step 7: Commit**

~~~bash
git add frontend/src/components/production-nodes/ProductionNodeWorkbench.vue frontend/src/components/production-nodes/NodeListPanel.vue frontend/tests/unit/ProductionNodeWorkbench.spec.js
git commit -m "feat: add production node management workbench shell"
~~~

---

### Task 4: Add the node editor panel

**Files:**
- Create: frontend/src/components/production-nodes/NodeEditorPanel.vue
- Create: frontend/tests/unit/ProductionNodePanels.spec.js
- Modify: frontend/src/components/production-nodes/ProductionNodeWorkbench.vue

**Interfaces:**
- Consumes: nodeForm ref value, processOptions, calendars, canManage permission, saving state, resetNodeForm, editNode, and saveNode.
- Produces: dirty-change event and saved event.

- [ ] **Step 1: Write failing editor tests**

~~~javascript
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import NodeEditorPanel from '@/components/production-nodes/NodeEditorPanel.vue'

it('locks the process for existing nodes and emits dirty changes', async () => {
  const form = {
    id: 11,
    process_id: 7,
    node_code: 'WELD-01',
    node_name: '焊接-01',
    capacity_mode: 'exclusive',
    calendar_id: 1,
    status: 'active',
    reason: '',
    idempotency_key: 'node-11-update',
  }
  const wrapper = mount(NodeEditorPanel, {
    props: {
      form,
      processOptions: [{ id: 7, name: '焊接' }],
      calendars: [{ id: 1, calendar_name: '九小时工作制' }],
      canManage: true,
      saving: false,
      onSave: vi.fn(),
    },
  })

  expect(wrapper.get('[data-test="node-process"]').attributes('disabled')).toBeDefined()
  await wrapper.get('[data-test="node-name"]').setValue('焊接主节点')
  expect(wrapper.emitted('dirty-change').at(-1)).toEqual([true])
})
~~~

- [ ] **Step 2: Run panel tests and verify RED**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/ProductionNodePanels.spec.js
~~~

Expected: FAIL because NodeEditorPanel.vue does not exist.

- [ ] **Step 3: Implement the editor**

Keep useProductionNodes as the only form owner. Track a snapshot of the supplied reactive form without creating a second editable copy:

~~~javascript
const initialDigest = ref(JSON.stringify(props.form))

watch(
  () => props.form,
  value => {
    initialDigest.value = JSON.stringify(value || {})
    emit('dirty-change', false)
  },
  { deep: true },
)

watch(
  () => props.form,
  value => emit('dirty-change', JSON.stringify(value) !== initialDigest.value),
  { deep: true },
)

async function submit() {
  const result = await props.onSave()
  if (!result) return
  initialDigest.value = JSON.stringify(props.form)
  emit('dirty-change', false)
  emit('saved', result)
}
~~~

Bind controls directly to form fields such as form.node_name and form.capacity_mode. Because the controller owns the form object, a failed request naturally preserves the current user input.

Render all current node fields with explicit labels and data-test selectors. Hide form controls and show read-only values when canManage is false. Disable submit while saving.

- [ ] **Step 4: Wire the editor into the workbench**

When the user clicks create:

~~~javascript
function openCreate() {
  actions.resetNodeForm()
  workbench.selectedNodeId.value = null
  workbench.markDirty(false)
  workbench.requestTab('editor')
}
~~~

When editing a selected node:

~~~javascript
function openEdit(node) {
  actions.editNode(node)
  workbench.selectedNodeId.value = node.id
  workbench.markDirty(false)
  workbench.requestTab('editor')
}
~~~

Pass dirty-change to workbench.markDirty. On successful save, reload nodes, reselect the returned node where available, and clear dirty state.

- [ ] **Step 5: Run editor and shell tests**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/ProductionNodePanels.spec.js frontend/tests/unit/ProductionNodeWorkbench.spec.js
~~~

Expected: all tests PASS.

- [ ] **Step 6: Commit**

~~~bash
git add frontend/src/components/production-nodes/NodeEditorPanel.vue frontend/src/components/production-nodes/ProductionNodeWorkbench.vue frontend/tests/unit/ProductionNodePanels.spec.js
git commit -m "feat: add production node editor panel"
~~~

---

### Task 5: Add the calendar panel

**Files:**
- Create: frontend/src/components/production-nodes/NodeCalendarPanel.vue
- Modify: frontend/src/components/production-nodes/ProductionNodeWorkbench.vue
- Modify: frontend/tests/unit/ProductionNodePanels.spec.js

**Interfaces:**
- Consumes: selected node, matching base calendar, override form, override rows, loading/error/saving state, loadOverrides, prepareOverride, createCalendarOverride, and cancelOverride.
- Produces: dirty-change and saved events.

- [ ] **Step 1: Write failing calendar tests**

~~~javascript
it('renders the base calendar, retries failed loads, and creates an override', async () => {
  const onRetry = vi.fn()
  const onSave = vi.fn().mockResolvedValue({ id: 91 })
  const wrapper = mount(NodeCalendarPanel, {
    props: {
      node: { id: 11, calendar_id: 3 },
      calendar: { id: 3, calendar_name: '生产九小时日历', daily_minutes: 540 },
      overrides: [],
      form: {
        production_node_id: 11,
        start_at: '',
        end_at: '',
        override_type: 'maintenance',
        reason: '',
        idempotency_key: 'calendar-11',
      },
      loading: false,
      error: '日历读取失败',
      saving: false,
      canManage: true,
      onRetry,
      onSave,
      onCancelOverride: vi.fn(),
    },
  })

  expect(wrapper.text()).toContain('生产九小时日历')
  expect(wrapper.text()).toContain('540')
  await wrapper.get('[data-test="calendar-retry"]').trigger('click')
  expect(onRetry).toHaveBeenCalled()
})
~~~

- [ ] **Step 2: Run calendar tests and verify RED**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/ProductionNodePanels.spec.js
~~~

Expected: FAIL because NodeCalendarPanel.vue does not exist.

- [ ] **Step 3: Implement the calendar panel**

Render three explicit regions:

1. Base-calendar summary with calendar name and effective minutes.
2. Override list ordered newest first with type, start, end, status, reason, and cancel button.
3. Add-override form with start, end, type, reason, and idempotency key.

The component must not call the API directly. It invokes onRetry, onSave, and onCancelOverride props and emits dirty-change based on a local form digest.

- [ ] **Step 4: Lazy-load calendar data on tab entry**

In ProductionNodeWorkbench:

~~~javascript
async function enterTab(tab, node) {
  if (!node) return
  if (tab === 'calendar') {
    actions.prepareOverride(node)
    await actions.loadOverrides(node)
  }
  if (tab === 'capabilities') {
    await actions.loadCapabilities(node)
  }
}
~~~

Do not load overrides for all nodes when opening the workbench.

- [ ] **Step 5: Run controller, calendar, and shell tests**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/useProductionNodes.spec.js frontend/tests/unit/ProductionNodePanels.spec.js frontend/tests/unit/ProductionNodeWorkbench.spec.js
~~~

Expected: all selected tests PASS.

- [ ] **Step 6: Commit**

~~~bash
git add frontend/src/components/production-nodes/NodeCalendarPanel.vue frontend/src/components/production-nodes/ProductionNodeWorkbench.vue frontend/tests/unit/ProductionNodePanels.spec.js
git commit -m "feat: add production node calendar panel"
~~~

---

### Task 6: Add the capability panel

**Files:**
- Create: frontend/src/components/production-nodes/NodeCapabilityPanel.vue
- Modify: frontend/src/components/production-nodes/ProductionNodeWorkbench.vue
- Modify: frontend/tests/unit/ProductionNodePanels.spec.js

**Interfaces:**
- Consumes: selected node capacity mode, capability form, loading/error/saving state, addCapability, removeCapability, saveCapabilities, and retry callback.
- Produces: dirty-change and saved events.

- [ ] **Step 1: Write failing capability tests**

~~~javascript
it('shows batch fields only for batch nodes and preserves capability rows on save failure', async () => {
  const onSave = vi.fn().mockResolvedValue(null)
  const wrapper = mount(NodeCapabilityPanel, {
    props: {
      node: { id: 11, capacity_mode: 'exclusive' },
      form: {
        production_node_id: 11,
        node_label: 'WELD-01 · 焊接-01',
        capabilities: [{ product_family: 'HOUSING', status: 'active' }],
        reason: '',
        idempotency_key: 'capability-11',
      },
      loading: false,
      error: '',
      saving: false,
      canManage: true,
      onAdd: vi.fn(),
      onRemove: vi.fn(),
      onSave,
      onRetry: vi.fn(),
    },
  })

  expect(wrapper.find('[data-test="batch-minutes"]').exists()).toBe(false)
  await wrapper.get('[data-test="capability-product-family"]').setValue('SB121')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.get('[data-test="capability-product-family"]').element.value).toBe('SB121')
})
~~~

- [ ] **Step 2: Run capability tests and verify RED**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/ProductionNodePanels.spec.js
~~~

Expected: FAIL because NodeCapabilityPanel.vue does not exist.

- [ ] **Step 3: Implement capability rows**

Keep the controller capabilityForm as the single editable object and track its digest:

~~~javascript
const initialDigest = ref(JSON.stringify(props.form))
watch(
  () => props.form,
  value => emit(
    'dirty-change',
    JSON.stringify(value || {}) !== initialDigest.value,
  ),
  { deep: true },
)
~~~

Every row renders product ID, product family, material code, specification, route version ID, process version ID, and status. Render max batch quantity, batch minutes, changeover minutes, and mixed-order checkbox only when node.capacity_mode equals batch.

Bind row inputs directly to form.capabilities[index]. Use a responsive grid:

~~~css
.capability-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
}
@media (max-width: 899px) {
  .capability-row { grid-template-columns: 1fr; }
}
~~~

- [ ] **Step 4: Wire save and retry behavior**

On successful save, update initialDigest from the refreshed manager form and clear dirty state. On failure, keep the controller rows and reason unchanged. Retry calls actions.loadCapabilities(selectedNode).

- [ ] **Step 5: Run all production-node unit tests**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/useProductionNodes.spec.js frontend/tests/unit/useProductionNodeWorkbench.spec.js frontend/tests/unit/ProductionNodeWorkbench.spec.js frontend/tests/unit/ProductionNodePanels.spec.js
~~~

Expected: all selected tests PASS.

- [ ] **Step 6: Commit**

~~~bash
git add frontend/src/components/production-nodes/NodeCapabilityPanel.vue frontend/src/components/production-nodes/ProductionNodeWorkbench.vue frontend/tests/unit/ProductionNodePanels.spec.js
git commit -m "feat: add production node capability panel"
~~~

---

### Task 7: Integrate the workbench into production scheduling and complete acceptance

**Files:**
- Modify: frontend/src/composables/useGantt.js
- Modify: frontend/src/views/GanttChart.vue:1-420
- Modify: frontend/tests/unit/GanttChartProductionNodes.spec.js
- Create: frontend/tests/e2e/production-node-workbench.spec.js

**Interfaces:**
- Consumes: nodeManager from Task 1 and ProductionNodeWorkbench from Tasks 3-6.
- Produces: the final scheduling-page workflow with no inline long production-node modal.

- [ ] **Step 1: Write the failing Gantt integration test**

Extend createState with productionNodeManager and assert that the new workbench is present while the old stacked forms are absent:

~~~javascript
it('delegates production-node management to the viewport workbench', () => {
  const wrapper = mount(GanttChart, { attachTo: document.body })

  expect(document.body.querySelector('[data-test="production-node-workbench"]')).not.toBeNull()
  expect(wrapper.find('[data-test="legacy-node-manager-form"]').exists()).toBe(false)
  expect(document.body.textContent).toContain('节点列表')
  expect(document.body.textContent).toContain('节点编辑')
  expect(document.body.textContent).toContain('工作日历')
  expect(document.body.textContent).toContain('能力限制')
})
~~~

- [ ] **Step 2: Run the Gantt test and verify RED**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/GanttChartProductionNodes.spec.js
~~~

Expected: FAIL because GanttChart still contains the old inline modal.

- [ ] **Step 3: Expose nodeManager from useGantt**

After constructing nodes:

~~~javascript
const nodes = useProductionNodes({
  canManageNodes,
  canManageCapabilities,
  canManageCalendars,
})
~~~

Return both the grouped facade and existing flat fields:

~~~javascript
return {
  ...data,
  ...editor,
  ...nodes,
  ...capacity,
  ...batch,
  ...imageExport,
  productionNodeManager: nodes.nodeManager,
  processOptions: capacity.processOptions,
  canManageNodes,
  canManageCapabilities,
  canManageCalendars,
  canManageDowntime,
  onKeyDown,
}
~~~

Preserving the flat node refs keeps useGanttCapacity and existing tests compatible.

- [ ] **Step 4: Replace the inline modal**

Import the component:

~~~javascript
import ProductionNodeWorkbench from '@/components/production-nodes/ProductionNodeWorkbench.vue'
~~~

Register it in GanttChart and replace the current block beginning at the Production Node Modal comment with:

~~~vue
<ProductionNodeWorkbench
  v-model="showNodeMgr"
  :manager="productionNodeManager"
  :process-options="processOptions"
  @closed="loadCapacity"
/>
~~~

Remove the old node form, node list, calendar form, and capability form from GanttChart.vue. Do not change the schedule adjustment modal or downtime section.

- [ ] **Step 5: Run unit and architecture tests**

Run:

~~~bash
npx vitest run --config vitest.config.js frontend/tests/unit/GanttChartProductionNodes.spec.js frontend/tests/unit/useGantt.spec.js frontend/tests/unit/useProductionNodes.spec.js frontend/tests/unit/useProductionNodeWorkbench.spec.js frontend/tests/unit/ProductionNodeWorkbench.spec.js frontend/tests/unit/ProductionNodePanels.spec.js
npm run check:api
npm run check:imports
~~~

Expected: all selected tests PASS; API facade and import-cycle checks PASS.

- [ ] **Step 6: Write the browser acceptance test**

~~~javascript
import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'

test('production node workbench remains viewport-fixed and responsive', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const nodes = Array.from({ length: 25 }, (_, index) => ({
    id: index + 1,
    process_id: index < 10 ? 7 : 8,
    process_name: index < 10 ? '焊接' : '铆接',
    node_code: 'NODE-' + String(index + 1).padStart(2, '0'),
    node_name: '生产节点-' + String(index + 1).padStart(2, '0'),
    status: 'active',
    capacity_mode: 'exclusive',
    calendar_id: 1,
  }))
  await page.route(/\/api\/production-nodes(?:\?.*)?$/, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ nodes }),
  }))
  await page.setViewportSize({ width: 1366, height: 768 })
  await loginAdmin(page)
  await openSidebarPage(page, '生产排程', '生产排程')
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))

  const trigger = page.getByRole('button', { name: /生产节点管理/ })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '生产节点管理' })
  await expect(dialog).toBeVisible()

  const desktopBox = await dialog.boundingBox()
  expect(desktopBox.x).toBeGreaterThanOrEqual(0)
  expect(desktopBox.y).toBeGreaterThanOrEqual(0)
  expect(desktopBox.x + desktopBox.width).toBeLessThanOrEqual(1366)
  expect(desktopBox.y + desktopBox.height).toBeLessThanOrEqual(768)
  await expect(dialog.locator('.node-workbench__header')).toBeVisible()
  await expect(dialog.locator('.node-workbench__footer')).toBeVisible()
  await expect(dialog.locator('[data-test^="node-item-"]')).toHaveCount(25)
  await dialog.getByPlaceholder('搜索节点编码或名称').fill('NODE-25')
  await expect(dialog.locator('[data-test^="node-item-"]')).toHaveCount(1)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(dialog).toHaveClass(/node-workbench/)
  await expect(dialog.getByLabel('选择生产节点')).toBeVisible()
  const mobileBox = await dialog.boundingBox()
  expect(Math.abs(mobileBox.width - 390)).toBeLessThanOrEqual(1)
  expect(Math.abs(mobileBox.height - 844)).toBeLessThanOrEqual(1)

  await dialog.getByRole('button', { name: '关闭生产节点管理' }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.locator(':focus')).toBeVisible()

  await dialog.getByRole('button', { name: '关闭生产节点管理' }).click()
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
  expect(failures).toEqual([])
})
~~~

- [ ] **Step 7: Run the browser test**

Run:

~~~bash
npx playwright test frontend/tests/e2e/production-node-workbench.spec.js
~~~

Expected: one browser test PASS with no page errors or HTTP 500 responses.

- [ ] **Step 8: Run the complete frontend verification**

Run:

~~~bash
npm run test:unit
npm run build
~~~

Expected:

- all frontend unit tests PASS;
- API facade check reports no duplicate/missing methods;
- import-cycle check reports no cycles;
- Vite production build succeeds.

- [ ] **Step 9: Inspect the final diff**

Run:

~~~bash
git diff --check
git status --short
git diff --stat github/master...HEAD
~~~

Expected: no whitespace errors; only the planned production-node frontend files and tests are changed.

- [ ] **Step 10: Commit**

~~~bash
git add frontend/src/components/production-nodes frontend/src/composables/gantt/useProductionNodeWorkbench.js frontend/src/composables/gantt/useProductionNodes.js frontend/src/composables/useGantt.js frontend/src/views/GanttChart.vue frontend/tests/unit frontend/tests/e2e/production-node-workbench.spec.js
git commit -m "feat: redesign production node management workbench"
~~~

---

## Final Review Checklist

- [ ] Every confirmed requirement in the design spec maps to a task and a test.
- [ ] GanttChart.vue no longer contains the long production-node management forms.
- [ ] Only one useProductionNodes instance owns node state.
- [ ] No backend, migration, permission-catalog, or database files changed.
- [ ] Overlay clicks do not close the workbench.
- [ ] Dirty guards cover tab, node, Escape, and close transitions.
- [ ] Desktop and small-screen layouts meet the 900px breakpoint contract.
- [ ] Focus is trapped while open and returns to the trigger after close.
- [ ] Panel errors remain local and retryable.
- [ ] Stale capability/calendar requests cannot overwrite a newer selected node.
- [ ] Frontend unit tests, browser acceptance, API facade check, import-cycle check, and production build pass.
