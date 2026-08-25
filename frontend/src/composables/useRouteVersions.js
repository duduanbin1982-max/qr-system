import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'


export const ROUTE_VERSION_STATUS_LABELS = Object.freeze({
  draft: '草稿',
  pending_approval: '待审批',
  published: '已发布',
  rejected: '已驳回',
  superseded: '已取代',
  retired: '已退休',
})

export const ROUTE_LIFECYCLE_LABELS = Object.freeze({
  active: '生效中',
  retirement_pending: '退休审批中',
  retired: '已退休',
  reactivation_pending: '重新启用审批中',
})

export function routeVersionStatusLabel(status) {
  return ROUTE_VERSION_STATUS_LABELS[status] || status || '-'
}

export function routeLifecycleLabel(status) {
  return ROUTE_LIFECYCLE_LABELS[status] || status || '-'
}

function commandKey(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  return `${prefix}:${uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

export function routeVersionErrorMessage(error) {
  const actions = {
    refresh_route_version: '路线版本已变化，请刷新完整详情后重试',
    select_different_approver: '制单人与批准人必须不同，请切换批准账号',
    resolve_release_dependencies: '发布依赖尚未完成，请处理工序、路线和工价后重试',
    create_new_revision: '已发布版本保持只读，请创建新的路线修订版',
  }
  return actions[error?.action] || error?.message || '路线版本操作失败'
}

function versionById(versions, versionId) {
  return versions.find(item => Number(item.id) === Number(versionId)) || null
}

function normalizeItems(items) {
  return (items || []).map((item, index) => ({
    process_id: Number(item.process_id),
    process_version_id: Number(item.process_version_id),
    seq_order: Number(item.seq_order ?? ((index + 1) * 10)),
    is_required: item.is_required === 0 ? 0 : 1,
    required_audit: item.required_audit ? 1 : 0,
  }))
}

function normalizeRouteForm(form) {
  return {
    name: String(form?.name || '').trim(),
    category: String(form?.category || '').trim(),
    description: String(form?.description || ''),
    items: normalizeItems(form?.items),
  }
}

export function useRouteVersions() {
  const selectedRoute = ref(null)
  const root = ref(null)
  const versions = ref([])
  const events = ref([])
  const selectedVersion = ref(null)
  const impact = ref(null)
  const priceVersions = ref([])
  const referencePriceVersions = ref([])
  const loadingDetail = ref(false)
  const loadingContext = ref(false)
  const busy = ref(false)
  const operationError = ref('')
  const contextError = ref('')

  const currentVersion = computed(() => {
    const currentId = root.value?.current_effective_version_id
    return versionById(versions.value, currentId)
      || versions.value.find(item => item.status === 'published')
      || null
  })
  const openVersion = computed(() => versions.value.find(
    item => item.status === 'draft' || item.status === 'pending_approval'
  ) || null)
  const historicalVersions = computed(() => versions.value.filter(
    item => item.id !== currentVersion.value?.id && item.id !== openVersion.value?.id
  ))
  const comparisonBase = computed(() => {
    const selected = selectedVersion.value
    if (!selected) return null
    if (selected.supersedes_version_id) {
      return versionById(versions.value, selected.supersedes_version_id)
    }
    return versions.value
      .filter(item => Number(item.version) < Number(selected.version))
      .sort((a, b) => Number(b.version) - Number(a.version))[0] || null
  })
  const coverageRows = computed(() => (selectedVersion.value?.items || []).map(node => {
    const exactPrices = priceVersions.value.filter(price => (
      Number(price.route_version_id) === Number(selectedVersion.value?.id)
      && Number(price.process_version_id) === Number(node.process_version_id)
    ))
    const referencePrice = referencePriceVersions.value
      .filter(price => (
        Number(price.process_id) === Number(node.process_id)
        && price.status === 'approved'
      ))
      .sort((a, b) => `${b.valid_from || ''}:${b.id}`.localeCompare(`${a.valid_from || ''}:${a.id}`))[0] || null
    const coverageStatus = exactPrices.some(price => price.status === 'approved')
      ? 'approved'
      : exactPrices.some(price => price.status === 'draft')
        ? 'draft'
        : exactPrices.some(price => price.status === 'voided') ? 'voided' : 'missing'
    return {
      ...node,
      price_versions: exactPrices,
      reference_price: selectedVersion.value?.status === 'draft' ? referencePrice : null,
      coverage_status: coverageStatus,
    }
  }))

  async function loadSelectedContext(versionId) {
    if (!versionId) {
      impact.value = null
      priceVersions.value = []
      referencePriceVersions.value = []
      return
    }
    loadingContext.value = true
    contextError.value = ''
    const baseVersionId = selectedVersion.value?.status === 'draft'
      ? comparisonBase.value?.id
      : null
    const [impactResult, priceResult, referencePriceResult] = await Promise.allSettled([
      api.domains.processRouteVersions.getRouteVersionImpact(versionId),
      api.domains.wages.listRoutePriceVersions({ route_version_id: versionId }),
      baseVersionId
        ? api.domains.wages.listRoutePriceVersions({ route_version_id: baseVersionId })
        : Promise.resolve({ versions: [] }),
    ])
    if (impactResult.status === 'fulfilled') {
      impact.value = impactResult.value.impact || impactResult.value
    } else {
      impact.value = null
      contextError.value = routeVersionErrorMessage(impactResult.reason)
    }
    referencePriceVersions.value = referencePriceResult.status === 'fulfilled'
      ? (referencePriceResult.value.versions || referencePriceResult.value || [])
      : []
    if (priceResult.status === 'fulfilled') {
      priceVersions.value = priceResult.value.versions || priceResult.value || []
    } else {
      priceVersions.value = []
      contextError.value ||= routeVersionErrorMessage(priceResult.reason)
    }
    loadingContext.value = false
  }

  async function selectVersion(versionOrId) {
    selectedVersion.value = typeof versionOrId === 'object'
      ? versionOrId
      : versionById(versions.value, versionOrId)
    await loadSelectedContext(selectedVersion.value?.id)
    return selectedVersion.value
  }

  async function loadRoute(routeId, preferredVersionId = null) {
    loadingDetail.value = true
    operationError.value = ''
    try {
      const payload = await api.domains.processRouteVersions.listRouteVersions(routeId)
      root.value = payload.route || null
      versions.value = [...(payload.versions || [])].sort((a, b) => Number(b.version) - Number(a.version))
      events.value = payload.events || []
      selectedRoute.value = { ...(selectedRoute.value || {}), ...(root.value || {}), id: root.value?.id || routeId }
      const preferred = versionById(versions.value, preferredVersionId)
      await selectVersion(preferred || openVersion.value || currentVersion.value || versions.value[0])
      return payload
    } catch (error) {
      operationError.value = routeVersionErrorMessage(error)
      throw error
    } finally {
      loadingDetail.value = false
    }
  }

  async function openRoute(route) {
    selectedRoute.value = route ? { ...route } : null
    if (!route?.id) return null
    return loadRoute(route.id, route.route_version_id)
  }

  async function runOperation(callback) {
    if (busy.value) return null
    busy.value = true
    operationError.value = ''
    try {
      return await callback()
    } catch (error) {
      operationError.value = routeVersionErrorMessage(error)
      throw error
    } finally {
      busy.value = false
    }
  }

  async function createRoute(form) {
    return runOperation(async () => {
      const result = await api.domains.processRouteVersions.createVersionedRoute({
        ...normalizeRouteForm(form),
        revision_reason: String(form?.revision_reason || '').trim(),
        idempotency_key: commandKey('route-create'),
      })
      selectedRoute.value = result.root
      await loadRoute(result.root.id, result.version.id)
      return result
    })
  }

  async function createRevision(form) {
    return runOperation(async () => {
      const routeId = root.value?.id || selectedRoute.value?.id
      if (!routeId) throw new Error('未选择路线')
      const result = await api.domains.processRouteVersions.createRouteRevision(routeId, {
        row_version: Number(root.value?.row_version || 0),
        ...normalizeRouteForm(form),
        revision_reason: String(form?.revision_reason || '').trim(),
        idempotency_key: commandKey('route-revision'),
      })
      await loadRoute(routeId, result.id)
      return result
    })
  }

  async function updateDraft(form) {
    return runOperation(async () => {
      const version = selectedVersion.value
      if (!version || version.status !== 'draft') throw new Error('仅草稿路线版本允许编辑')
      const result = await api.domains.processRouteVersions.updateRouteVersion(version.id, {
        row_version: Number(version.row_version || 0),
        ...normalizeRouteForm(form),
      })
      await loadRoute(version.process_route_id, result.id)
      return result
    })
  }

  async function transition(action, reason = '') {
    return runOperation(async () => {
      const version = selectedVersion.value
      if (!version) throw new Error('未选择路线版本')
      const payload = {
        row_version: Number(version.row_version || 0),
        idempotency_key: commandKey(`route-${action}`),
      }
      if (action === 'reject') payload.reason = String(reason || '').trim()
      const method = action === 'submit' ? 'submitRouteVersion' : 'rejectRouteVersion'
      const result = await api.domains.processRouteVersions[method](version.id, payload)
      await loadRoute(version.process_route_id, result.id)
      return result
    })
  }

  function validatePriceDispositions(dispositions) {
    const nodes = selectedVersion.value?.items || []
    const requiredIds = [...new Set(nodes.map(node => Number(node.process_id)))]
    const byProcess = new Map((dispositions || []).map(item => [Number(item.process_id), item]))
    const normalized = requiredIds.map(processId => {
      const item = byProcess.get(processId)
      if (!item || !['price_version', 'not_applicable'].includes(item.disposition)) {
        throw new Error('每个路线节点都必须完成工价处置后才能批准发布')
      }
      if (item.disposition === 'not_applicable') {
        const reason = String(item.reason || '').trim()
        if (!reason) throw new Error('工价不适用处置必须填写原因')
        return { process_id: processId, disposition: 'not_applicable', reason }
      }
      const priceVersionId = Number(item.price_version_id)
      const node = nodes.find(candidate => Number(candidate.process_id) === processId)
      const exact = priceVersions.value.find(price => (
        Number(price.id) === priceVersionId
        && Number(price.route_version_id) === Number(selectedVersion.value.id)
        && Number(price.process_version_id) === Number(node?.process_version_id)
      ))
      if (!priceVersionId || (priceVersions.value.length && !exact)) {
        throw new Error('工价处置必须选择与路线节点完全匹配的工价版本')
      }
      return { process_id: processId, disposition: 'price_version', price_version_id: priceVersionId }
    })
    return { required_price_process_ids: requiredIds, price_dispositions: normalized }
  }

  async function approveSelected(dispositions) {
    return runOperation(async () => {
      const version = selectedVersion.value
      if (!version) throw new Error('未选择路线版本')
      const pricePayload = validatePriceDispositions(dispositions)
      const result = await api.domains.processRouteVersions.approveRouteVersion(version.id, {
        row_version: Number(version.row_version || 0),
        idempotency_key: commandKey('route-approve'),
        ...pricePayload,
      })
      await loadRoute(version.process_route_id, result.id)
      return result
    })
  }

  async function requestLifecycle(action, reason) {
    return runOperation(async () => {
      const routeId = root.value?.id || selectedRoute.value?.id
      if (!routeId) throw new Error('未选择路线')
      const method = action === 'retire' ? 'requestRouteRetirement' : 'requestRouteReactivation'
      const result = await api.domains.processRouteVersions[method](routeId, {
        row_version: Number(root.value?.row_version || 0),
        reason: String(reason || '').trim(),
        idempotency_key: commandKey(`route-${action}`),
      })
      await loadRoute(routeId, selectedVersion.value?.id)
      return result
    })
  }

  function reset() {
    selectedRoute.value = null
    root.value = null
    versions.value = []
    events.value = []
    selectedVersion.value = null
    impact.value = null
    priceVersions.value = []
    operationError.value = ''
    contextError.value = ''
  }

  return {
    selectedRoute,
    root,
    versions,
    events,
    selectedVersion,
    currentVersion,
    openVersion,
    historicalVersions,
    comparisonBase,
    impact,
    priceVersions,
    referencePriceVersions,
    coverageRows,
    loadingDetail,
    loadingContext,
    busy,
    operationError,
    contextError,
    loadRoute,
    openRoute,
    selectVersion,
    createRoute,
    createRevision,
    updateDraft,
    transition,
    validatePriceDispositions,
    approveSelected,
    requestLifecycle,
    reset,
  }
}
