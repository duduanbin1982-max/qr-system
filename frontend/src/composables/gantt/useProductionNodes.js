import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


function freshNodeForm() {
  return {
    id: null,
    process_id: '',
    node_code: '',
    node_name: '',
    capacity_mode: 'exclusive',
    status: 'active',
    calendar_id: '',
    row_version: 1,
    reason: '',
    idempotency_key: '',
  }
}

function freshOverrideForm() {
  return {
    production_node_id: '',
    start_at: '',
    end_at: '',
    override_type: 'unavailable',
    reason: '',
    idempotency_key: '',
  }
}

function freshCapability() {
  return {
    product_id: null,
    product_family: '',
    material_code: '',
    specification: '',
    route_version_id: null,
    process_version_id: null,
    max_batch_quantity: null,
    batch_minutes: null,
    changeover_minutes: 0,
    allow_mixed_orders: false,
    status: 'active',
  }
}

function freshCapabilityForm() {
  return {
    production_node_id: '',
    node_label: '',
    capabilities: [],
    reason: '',
    idempotency_key: '',
  }
}

function freshNodeSummary(nodeId = '') {
  return {
    production_node_id: nodeId || '',
    capability_count: 0,
    future_override_count: 0,
  }
}

function commandKey(prefix, id = 'new') {
  return `${prefix}-${id}-${Date.now()}`
}

function capabilityFormFrom(node, capabilities) {
  return {
    production_node_id: node.id,
    node_label: [node.node_code, node.node_name].filter(Boolean).join(' · '),
    capabilities: capabilities.map(item => ({
      product_id: item.product_id ?? null,
      product_family: item.product_family || '',
      material_code: item.material_code || '',
      specification: item.specification || '',
      route_version_id: item.route_version_id ?? null,
      process_version_id: item.process_version_id ?? null,
      max_batch_quantity: item.max_batch_quantity ?? null,
      batch_minutes: item.batch_minutes ?? null,
      changeover_minutes: Number(item.changeover_minutes || 0),
      allow_mixed_orders: Boolean(item.allow_mixed_orders),
      status: item.status || 'active',
    })),
    reason: '',
    idempotency_key: commandKey('production-node-capabilities', node.id),
  }
}

const clone = value => JSON.parse(JSON.stringify(value))
const nodeKey = value => (value === null || value === undefined || value === '' ? null : String(value))

function futureOverrideCount(overrides) {
  const now = Date.now()
  return overrides.filter(item => {
    if (['cancelled', 'canceled', 'expired', 'completed'].includes(String(item.status || '').toLowerCase())) {
      return false
    }
    const end = Date.parse(item.end_at || item.start_at || '')
    return Number.isFinite(end) && end > now
  }).length
}


export function useProductionNodes({
  canViewNodes = ref(true),
  canManageNodes,
  canManageCapabilities,
  canManageCalendars,
}) {
  const productionNodes = ref([])
  const productionCalendars = ref([])
  const nodesLoading = ref(false)
  const nodesError = ref('')
  const calendarsLoading = ref(false)
  const calendarsError = ref('')
  const showNodeMgr = ref(false)
  const currentNodeId = ref(null)
  const contextGeneration = ref(0)

  const nodeForm = ref(freshNodeForm())
  const nodeSaving = ref(false)
  const overrideForm = ref(freshOverrideForm())
  const nodeOverrides = ref([])
  const overridesLoading = ref(false)
  const overridesError = ref('')
  const overrideSaving = ref(false)
  const capabilityForm = ref(freshCapabilityForm())
  const capabilitiesLoading = ref(false)
  const capabilitiesError = ref('')
  const capabilitySaving = ref(false)
  const nodeSummary = ref(freshNodeSummary())
  const nodeSummaryLoading = ref(false)
  const nodeSummaryError = ref('')

  let nodeBaseline = freshNodeForm()
  let overrideBaseline = freshOverrideForm()
  let capabilityBaseline = freshCapabilityForm()
  let nodeFormGeneration = 0
  let overrideFormGeneration = 0
  let capabilityFormGeneration = 0
  let capabilityCountVersion = 0
  let overrideCountVersion = 0
  const requestTokens = {
    nodes: 0,
    calendars: 0,
    summary: 0,
    capabilityLoad: 0,
    overrideLoad: 0,
    nodeSave: 0,
    capabilitySave: 0,
    overrideCreate: 0,
    overrideCancel: 0,
  }

  const nodesByProcess = computed(() => Object.values(
    productionNodes.value.reduce((groups, node) => {
      const key = String(node.process_id)
      if (!groups[key]) {
        groups[key] = {
          process_id: node.process_id,
          process_name: node.process_name || `工序 #${node.process_id}`,
          nodes: [],
        }
      }
      groups[key].nodes.push(node)
      return groups
    }, {}),
  ))

  function installNodeForm(form, { baseline = true } = {}) {
    nodeForm.value = form
    nodeFormGeneration = contextGeneration.value
    if (baseline) nodeBaseline = clone(form)
  }

  function installOverrideForm(form, { baseline = true } = {}) {
    overrideForm.value = form
    overrideFormGeneration = contextGeneration.value
    if (baseline) overrideBaseline = clone(form)
  }

  function installCapabilityForm(form, { baseline = true } = {}) {
    capabilityForm.value = form
    capabilityFormGeneration = contextGeneration.value
    if (baseline) capabilityBaseline = clone(form)
  }

  function capture(channel, targetNodeId = currentNodeId.value) {
    return {
      channel,
      nodeId: nodeKey(targetNodeId),
      generation: contextGeneration.value,
      token: ++requestTokens[channel],
    }
  }

  function contextIsCurrent(snapshot, { latest = true } = {}) {
    return nodeKey(currentNodeId.value) === snapshot.nodeId
      && contextGeneration.value === snapshot.generation
      && (!latest || requestTokens[snapshot.channel] === snapshot.token)
  }

  function clearDetailState(node = null) {
    installNodeForm(freshNodeForm())
    installOverrideForm(node ? {
      ...freshOverrideForm(),
      production_node_id: node.id,
      idempotency_key: commandKey('production-node-calendar', node.id),
    } : freshOverrideForm())
    installCapabilityForm(node ? capabilityFormFrom(node, []) : freshCapabilityForm())
    nodeOverrides.value = []
    overridesLoading.value = false
    overridesError.value = ''
    capabilitiesLoading.value = false
    capabilitiesError.value = ''
    nodeSummary.value = freshNodeSummary(node?.id)
    nodeSummaryLoading.value = false
    nodeSummaryError.value = ''
  }

  function selectNodeContext(node) {
    const nextId = nodeKey(node?.id)
    if (nodeKey(currentNodeId.value) === nextId) return node || null
    currentNodeId.value = node?.id ?? null
    contextGeneration.value += 1
    clearDetailState(node || null)
    return node || null
  }

  function resetWorkbenchSession() {
    currentNodeId.value = null
    contextGeneration.value += 1
    clearDetailState(null)
  }

  function rollbackPanel(tab) {
    if (tab === 'editor') {
      installNodeForm(clone(nodeBaseline), { baseline: false })
    } else if (tab === 'calendar') {
      installOverrideForm(clone(overrideBaseline), { baseline: false })
    } else if (tab === 'capabilities') {
      installCapabilityForm(clone(capabilityBaseline), { baseline: false })
    }
  }

  async function loadCalendars() {
    if (!canViewNodes.value) return null
    const requestId = ++requestTokens.calendars
    calendarsLoading.value = true
    calendarsError.value = ''
    try {
      const data = await api.domains.production.listScheduleCalendars()
      if (requestId !== requestTokens.calendars) return null
      const nextCalendars = data.calendars || data || []
      productionCalendars.value = nextCalendars
      return nextCalendars
    } catch (error) {
      if (requestId === requestTokens.calendars) {
        calendarsError.value = error?.message || '加载工作日历失败'
      }
      return null
    } finally {
      if (requestId === requestTokens.calendars) calendarsLoading.value = false
    }
  }

  async function loadNodes(params = {}) {
    if (!canViewNodes.value) return null
    const requestId = ++requestTokens.nodes
    nodesLoading.value = true
    nodesError.value = ''
    loadCalendars()
    try {
      const data = await api.domains.production.listProductionNodes({ limit: 500, ...params })
      if (requestId !== requestTokens.nodes) return null
      const nextNodes = data.nodes || data || []
      productionNodes.value = nextNodes
      return {
        nodes: nextNodes,
        calendars: productionCalendars.value,
      }
    } catch (error) {
      if (requestId === requestTokens.nodes) {
        nodesError.value = error?.message || '加载生产节点失败'
        showToast(nodesError.value, 'error')
      }
      return null
    } finally {
      if (requestId === requestTokens.nodes) nodesLoading.value = false
    }
  }

  function resetNodeForm(defaults = {}) {
    installNodeForm({
      ...freshNodeForm(),
      idempotency_key: commandKey('production-node'),
      ...defaults,
    })
  }

  function editNode(node) {
    if (!canManageNodes.value || !node?.id) return
    if (nodeKey(currentNodeId.value) !== nodeKey(node.id)) selectNodeContext(node)
    installNodeForm({
      id: node.id,
      process_id: node.process_id,
      node_code: node.node_code || '',
      node_name: node.node_name || '',
      capacity_mode: node.capacity_mode || 'exclusive',
      status: node.status || 'active',
      calendar_id: node.calendar_id || '',
      row_version: Number(node.row_version || 1),
      reason: '',
      idempotency_key: commandKey('production-node-update', node.id),
    })
    showNodeMgr.value = true
  }

  function upsertProductionNode(node) {
    if (!node?.id) return null
    const index = productionNodes.value.findIndex(item => nodeKey(item.id) === nodeKey(node.id))
    if (index === -1) {
      productionNodes.value = [...productionNodes.value, node]
      return node
    }
    const merged = { ...productionNodes.value[index], ...node }
    productionNodes.value = productionNodes.value.map((item, itemIndex) => (
      itemIndex === index ? merged : item
    ))
    return merged
  }

  async function saveNodeCommand() {
    const formRef = nodeForm.value
    const form = clone(formRef)
    if (!Number(form.process_id) || !String(form.node_code || '').trim()
      || !String(form.node_name || '').trim() || !Number(form.calendar_id)) {
      showToast('工序、节点编码、节点名称和工作日历必填', 'error')
      return null
    }
    if (!String(form.idempotency_key || '').trim()) {
      showToast('幂等键必填', 'error')
      return null
    }
    if (!String(form.reason || '').trim()) {
      showToast('生产节点变更原因必填', 'error')
      return null
    }
    const isCreate = !form.id
    const expectedCurrentNodeId = isCreate ? null : nodeKey(form.id)
    const snapshot = capture('nodeSave', currentNodeId.value)
    const formContextIsCurrent = () => (
      contextIsCurrent(snapshot)
      && nodeKey(currentNodeId.value) === expectedCurrentNodeId
      && nodeFormGeneration === snapshot.generation
      && nodeForm.value === formRef
    )
    if (!formContextIsCurrent()) return null
    const payload = {
      process_id: Number(form.process_id),
      node_code: String(form.node_code).trim(),
      node_name: String(form.node_name).trim(),
      capacity_mode: form.capacity_mode,
      status: form.status,
      calendar_id: Number(form.calendar_id),
      row_version: Number(form.row_version || 1),
      reason: String(form.reason || '').trim(),
      idempotency_key: String(form.idempotency_key).trim(),
    }
    try {
      const result = form.id
        ? await api.domains.production.updateProductionNode(form.id, payload)
        : await api.domains.production.createProductionNode(payload)
      upsertProductionNode(result)
      if (!formContextIsCurrent()) return null
      const refreshed = await loadNodes()
      if (!refreshed || !formContextIsCurrent()) return null
      const savedId = result?.id ?? form.id
      const savedNode = productionNodes.value.find(item => (
        savedId != null
          ? nodeKey(item.id) === nodeKey(savedId)
          : item.node_code === payload.node_code
      )) || null
      if (!savedNode) {
        nodesError.value = '保存成功，但刷新节点失败'
        return null
      }
      selectNodeContext(savedNode)
      editNode(savedNode)
      const completionContext = {
        nodeId: nodeKey(savedNode.id),
        generation: contextGeneration.value,
        form: nodeForm.value,
      }
      await loadNodeSummary(savedNode)
      if (nodeKey(currentNodeId.value) !== completionContext.nodeId
        || contextGeneration.value !== completionContext.generation
        || nodeForm.value !== completionContext.form) {
        return null
      }
      showToast(form.id ? '生产节点已更新' : '生产节点已创建')
      return result
    } catch (error) {
      if (formContextIsCurrent()) showToast(error.message || '保存生产节点失败', 'error')
      return null
    }
  }

  function prepareOverride(node) {
    if (!node?.id) return
    if (nodeKey(currentNodeId.value) !== nodeKey(node.id)) selectNodeContext(node)
    installOverrideForm({
      ...freshOverrideForm(),
      production_node_id: node.id,
      idempotency_key: commandKey('production-node-calendar', node.id),
    })
  }

  async function loadNodeSummary(node) {
    if (!canViewNodes.value || !node?.id) return null
    if (nodeKey(currentNodeId.value) !== nodeKey(node.id)) selectNodeContext(node)
    const snapshot = capture('summary', node.id)
    const summaryVersions = {
      capability: capabilityCountVersion,
      override: overrideCountVersion,
    }
    nodeSummaryLoading.value = true
    nodeSummaryError.value = ''
    try {
      const [capabilityData, overrideData] = await Promise.all([
        api.domains.production.listProductionNodeCapabilities(node.id),
        api.domains.production.listProductionNodeOverrides(node.id, { limit: 500 }),
      ])
      if (!contextIsCurrent(snapshot)) return null
      const capabilities = capabilityData.capabilities || []
      const overrides = overrideData.overrides || overrideData.items || []
      const nextSummary = {
        ...nodeSummary.value,
        production_node_id: node.id,
      }
      if (capabilityCountVersion === summaryVersions.capability) {
        nextSummary.capability_count = capabilities.length
      }
      if (overrideCountVersion === summaryVersions.override) {
        nextSummary.future_override_count = futureOverrideCount(overrides)
      }
      nodeSummary.value = nextSummary
      return nodeSummary.value
    } catch (error) {
      if (contextIsCurrent(snapshot)
        && capabilityCountVersion === summaryVersions.capability
        && overrideCountVersion === summaryVersions.override) {
        nodeSummaryError.value = error.message || '加载节点摘要失败'
      }
      return null
    } finally {
      if (contextIsCurrent(snapshot)) nodeSummaryLoading.value = false
    }
  }

  async function loadCapabilities(node) {
    if (!canViewNodes.value || !node?.id) return null
    if (nodeKey(currentNodeId.value) !== nodeKey(node.id)) selectNodeContext(node)
    const snapshot = capture('capabilityLoad', node.id)
    capabilitiesLoading.value = true
    capabilitiesError.value = ''
    try {
      const result = await api.domains.production.listProductionNodeCapabilities(node.id)
      if (!contextIsCurrent(snapshot)) return null
      const capabilities = result.capabilities || []
      installCapabilityForm(capabilityFormFrom(node, capabilities))
      if (nodeKey(nodeSummary.value.production_node_id) === snapshot.nodeId) {
        capabilityCountVersion += 1
        nodeSummary.value = { ...nodeSummary.value, capability_count: capabilities.length }
      }
      return result
    } catch (error) {
      if (contextIsCurrent(snapshot)) {
        capabilitiesError.value = error.message || '加载节点能力失败'
        showToast(capabilitiesError.value, 'error')
      }
      return null
    } finally {
      if (contextIsCurrent(snapshot)) capabilitiesLoading.value = false
    }
  }

  async function loadOverrides(node) {
    if (!canViewNodes.value || !node?.id) return null
    if (nodeKey(currentNodeId.value) !== nodeKey(node.id)) selectNodeContext(node)
    const snapshot = capture('overrideLoad', node.id)
    overridesLoading.value = true
    overridesError.value = ''
    try {
      const result = await api.domains.production.listProductionNodeOverrides(
        node.id,
        { limit: 200 },
      )
      if (!contextIsCurrent(snapshot)) return null
      const overrides = result.overrides || result.items || []
      nodeOverrides.value = overrides
      if (nodeKey(nodeSummary.value.production_node_id) === snapshot.nodeId) {
        overrideCountVersion += 1
        nodeSummary.value = {
          ...nodeSummary.value,
          future_override_count: futureOverrideCount(overrides),
        }
      }
      return result
    } catch (error) {
      if (contextIsCurrent(snapshot)) {
        overridesError.value = error.message || '加载节点日历例外失败'
        showToast(overridesError.value, 'error')
      }
      return null
    } finally {
      if (contextIsCurrent(snapshot)) overridesLoading.value = false
    }
  }

  async function createCalendarOverrideCommand() {
    const formRef = overrideForm.value
    const form = clone(formRef)
    const productionNodeId = Number(form.production_node_id)
    if (!productionNodeId) {
      showToast('请选择生产节点', 'error')
      return null
    }
    if (!form.start_at || !form.end_at || new Date(form.end_at) <= new Date(form.start_at)) {
      showToast('节点日历结束时间必须晚于开始时间', 'error')
      return null
    }
    if (!String(form.reason || '').trim()) {
      showToast('节点日历调整原因必填', 'error')
      return null
    }
    const snapshot = capture('overrideCreate', productionNodeId)
    const formContextIsCurrent = () => (
      contextIsCurrent(snapshot)
      && overrideFormGeneration === snapshot.generation
      && nodeKey(form.production_node_id) === snapshot.nodeId
      && overrideForm.value === formRef
    )
    if (!formContextIsCurrent()) return null
    const payload = {
      start_at: form.start_at,
      end_at: form.end_at,
      override_type: form.override_type,
      reason: String(form.reason).trim(),
      idempotency_key: String(form.idempotency_key || commandKey('production-node-calendar')).trim(),
    }
    try {
      const result = await api.domains.production.createProductionNodeOverride(
        productionNodeId,
        payload,
      )
      if (!formContextIsCurrent()) return null
      const node = productionNodes.value.find(item => nodeKey(item.id) === snapshot.nodeId)
        || { id: productionNodeId }
      const refreshed = await loadOverrides(node)
      if (!refreshed || !formContextIsCurrent()) return null
      prepareOverride(node)
      showToast('生产节点日历例外已保存')
      return result
    } catch (error) {
      if (formContextIsCurrent()) showToast(error.message || '保存节点日历例外失败', 'error')
      return null
    }
  }

  async function cancelOverride(override, reason = '取消节点日历例外') {
    if (!canManageCalendars.value || !override?.id || overrideSaving.value) return null
    const overrideStatus = String(override.status || '').toLowerCase()
    if (overrideStatus && overrideStatus !== 'active') return null
    const targetNodeId = nodeKey(override.production_node_id)
    if (!targetNodeId || targetNodeId !== nodeKey(currentNodeId.value)
      || nodeKey(overrideForm.value.production_node_id) !== targetNodeId) {
      return null
    }
    const snapshot = capture('overrideCancel', override.production_node_id)
    const overrideFormVersion = overrideFormGeneration
    const overrideFormRef = overrideForm.value
    const overrideLoadToken = requestTokens.overrideLoad
    const overrideContextIsCurrent = ({ latestLoad = false } = {}) => (
      contextIsCurrent(snapshot)
      && overrideFormGeneration === overrideFormVersion
      && overrideForm.value === overrideFormRef
      && nodeKey(overrideForm.value.production_node_id) === snapshot.nodeId
      && (!latestLoad || requestTokens.overrideLoad === overrideLoadToken)
    )
    overrideSaving.value = true
    overridesError.value = ''
    try {
      const result = await api.domains.production.cancelProductionNodeOverride(
        override.id,
        {
          reason,
          idempotency_key: commandKey('production-node-calendar-cancel', override.id),
        },
      )
      if (!overrideContextIsCurrent({ latestLoad: true })) return null
      const node = productionNodes.value.find(item => nodeKey(item.id) === snapshot.nodeId)
        || { id: override.production_node_id }
      const refreshed = await loadOverrides(node)
      return refreshed && overrideContextIsCurrent() ? result : null
    } catch (error) {
      if (overrideContextIsCurrent({ latestLoad: true })) {
        overridesError.value = error.message || '取消节点日历例外失败'
        showToast(overridesError.value, 'error')
      }
      return null
    } finally {
      if (requestTokens.overrideCancel === snapshot.token) overrideSaving.value = false
    }
  }

  function capabilityContextIsWritable() {
    return nodeKey(currentNodeId.value) !== null
      && nodeKey(capabilityForm.value.production_node_id) === nodeKey(currentNodeId.value)
      && capabilityFormGeneration === contextGeneration.value
  }

  function addCapability() {
    if (!canManageCapabilities.value || !capabilityContextIsWritable()) return
    capabilityForm.value.capabilities.push(freshCapability())
  }

  function removeCapability(index) {
    if (!canManageCapabilities.value || !capabilityContextIsWritable()) return
    capabilityForm.value.capabilities.splice(index, 1)
  }

  async function saveCapabilitiesCommand() {
    const formRef = capabilityForm.value
    const form = clone(formRef)
    if (!Number(form.production_node_id)
      || nodeKey(form.production_node_id) !== nodeKey(currentNodeId.value)) {
      showToast('请先选择生产节点并加载能力配置', 'error')
      return null
    }
    if (!String(form.reason || '').trim()) {
      showToast('节点能力变更原因必填', 'error')
      return null
    }
    const snapshot = capture('capabilitySave', form.production_node_id)
    const contextForSaveIsCurrent = () => (
      contextIsCurrent(snapshot)
      && capabilityFormGeneration === snapshot.generation
    )
    if (!contextForSaveIsCurrent() || capabilityForm.value !== formRef) return null
    try {
      const result = await api.domains.production.replaceProductionNodeCapabilities(
        Number(form.production_node_id),
        {
          capabilities: form.capabilities.map(item => ({
            product_id: Number(item.product_id) || null,
            product_family: String(item.product_family || '').trim(),
            material_code: String(item.material_code || '').trim(),
            specification: String(item.specification || '').trim(),
            route_version_id: Number(item.route_version_id) || null,
            process_version_id: Number(item.process_version_id) || null,
            max_batch_quantity: Number(item.max_batch_quantity) || null,
            batch_minutes: Number(item.batch_minutes) || null,
            changeover_minutes: Number(item.changeover_minutes || 0),
            allow_mixed_orders: Boolean(item.allow_mixed_orders),
            status: item.status || 'active',
          })),
          reason: String(form.reason).trim(),
          idempotency_key: String(form.idempotency_key || '').trim(),
        },
      )
      if (!contextForSaveIsCurrent()) return null
      const node = productionNodes.value.find(item => nodeKey(item.id) === snapshot.nodeId)
      if (!node) return null
      const refreshed = await loadCapabilities(node)
      if (!refreshed || !contextForSaveIsCurrent() || capabilityForm.value === formRef) return null
      showToast('生产节点能力已更新')
      return result
    } catch (error) {
      if (contextForSaveIsCurrent()) showToast(error.message || '保存节点能力失败', 'error')
      return null
    }
  }

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

  const nodeManager = {
    state: {
      productionNodes,
      productionCalendars,
      nodesByProcess,
      nodesLoading,
      nodesError,
      calendarsLoading,
      calendarsError,
      currentNodeId,
      contextGeneration,
      nodeSummary,
      nodeSummaryLoading,
      nodeSummaryError,
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
      canViewNodes,
      canManageNodes,
      canManageCapabilities,
      canManageCalendars,
    },
    actions: {
      loadNodes,
      loadCalendars,
      selectNodeContext,
      loadNodeSummary,
      rollbackPanel,
      resetWorkbenchSession,
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

  resetNodeForm()

  return {
    productionNodes,
    productionCalendars,
    nodesByProcess,
    nodesLoading,
    nodesError,
    calendarsLoading,
    calendarsError,
    showNodeMgr,
    currentNodeId,
    contextGeneration,
    nodeSummary,
    nodeSummaryLoading,
    nodeSummaryError,
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
    loadNodes,
    loadCalendars,
    selectNodeContext,
    loadNodeSummary,
    rollbackPanel,
    resetWorkbenchSession,
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
    nodeManager,
  }
}
