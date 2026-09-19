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

function commandKey(prefix, id = 'new') {
  return `${prefix}-${id}-${Date.now()}`
}


export function useProductionNodes({
  canManageNodes,
  canManageCapabilities,
  canManageCalendars,
}) {
  const productionNodes = ref([])
  const productionCalendars = ref([])
  const nodesLoading = ref(false)
  const showNodeMgr = ref(false)
  const nodeForm = ref(freshNodeForm())
  const overrideForm = ref(freshOverrideForm())
  const capabilityForm = ref(freshCapabilityForm())
  const capabilitiesLoading = ref(false)

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

  async function loadNodes(params = {}) {
    nodesLoading.value = true
    try {
      const [data, calendarData] = await Promise.all([
        api.domains.production.listProductionNodes({ limit: 500, ...params }),
        api.domains.production.listScheduleCalendars(),
      ])
      productionNodes.value = data.nodes || data || []
      productionCalendars.value = calendarData.calendars || calendarData || []
      if (!overrideForm.value.production_node_id && productionNodes.value.length) {
        overrideForm.value.production_node_id = productionNodes.value[0].id
      }
    } catch (error) {
      console.warn('Production nodes load failed:', error)
      productionNodes.value = []
      productionCalendars.value = []
      showToast(error.message || '加载生产节点失败', 'error')
    } finally {
      nodesLoading.value = false
    }
  }

  function resetNodeForm(defaults = {}) {
    nodeForm.value = {
      ...freshNodeForm(),
      idempotency_key: commandKey('production-node'),
      ...defaults,
    }
  }

  function editNode(node) {
    if (!canManageNodes.value) return
    nodeForm.value = {
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
    }
    showNodeMgr.value = true
  }

  async function saveNode() {
    if (!canManageNodes.value) return null
    const form = nodeForm.value
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
      showToast(form.id ? '生产节点已更新' : '生产节点已创建')
      resetNodeForm({ process_id: form.process_id, calendar_id: form.calendar_id })
      await loadNodes()
      return result
    } catch (error) {
      showToast(error.message || '保存生产节点失败', 'error')
      return null
    }
  }

  function prepareOverride(node) {
    if (!canManageCalendars.value) return
    overrideForm.value = {
      ...freshOverrideForm(),
      production_node_id: node?.id || '',
      idempotency_key: commandKey('production-node-calendar', node?.id || 'node'),
    }
  }

  async function createCalendarOverride() {
    if (!canManageCalendars.value) return null
    const form = overrideForm.value
    if (!Number(form.production_node_id)) {
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
    const payload = {
      start_at: form.start_at,
      end_at: form.end_at,
      override_type: form.override_type,
      reason: String(form.reason).trim(),
      idempotency_key: String(form.idempotency_key || commandKey('production-node-calendar')).trim(),
    }
    try {
      const result = await api.domains.production.createProductionNodeOverride(
        Number(form.production_node_id), payload,
      )
      showToast('生产节点日历例外已保存')
      prepareOverride({ id: form.production_node_id })
      await loadNodes()
      return result
    } catch (error) {
      showToast(error.message || '保存节点日历例外失败', 'error')
      return null
    }
  }

  async function loadCapabilities(node) {
    if (!canManageCapabilities.value || !node?.id) return null
    capabilitiesLoading.value = true
    try {
      const result = await api.domains.production.listProductionNodeCapabilities(node.id)
      capabilityForm.value = {
        production_node_id: node.id,
        node_label: [node.node_code, node.node_name].filter(Boolean).join(' · '),
        capabilities: (result.capabilities || []).map(item => ({
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
      return result
    } catch (error) {
      showToast(error.message || '加载节点能力失败', 'error')
      return null
    } finally {
      capabilitiesLoading.value = false
    }
  }

  function addCapability() {
    if (!canManageCapabilities.value) return
    capabilityForm.value.capabilities.push(freshCapability())
  }

  function removeCapability(index) {
    if (!canManageCapabilities.value) return
    capabilityForm.value.capabilities.splice(index, 1)
  }

  async function saveCapabilities() {
    if (!canManageCapabilities.value) return null
    const form = capabilityForm.value
    if (!Number(form.production_node_id)) {
      showToast('请先选择生产节点并加载能力配置', 'error')
      return null
    }
    if (!String(form.reason || '').trim()) {
      showToast('节点能力变更原因必填', 'error')
      return null
    }
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
      showToast('生产节点能力已更新')
      const node = productionNodes.value.find(
        item => String(item.id) === String(form.production_node_id),
      )
      if (node) await loadCapabilities(node)
      return result
    } catch (error) {
      showToast(error.message || '保存节点能力失败', 'error')
      return null
    }
  }

  resetNodeForm()

  return {
    productionNodes,
    productionCalendars,
    nodesByProcess,
    nodesLoading,
    showNodeMgr,
    nodeForm,
    overrideForm,
    capabilityForm,
    capabilitiesLoading,
    loadNodes,
    resetNodeForm,
    editNode,
    saveNode,
    prepareOverride,
    createCalendarOverride,
    loadCapabilities,
    addCapability,
    removeCapability,
    saveCapabilities,
  }
}
