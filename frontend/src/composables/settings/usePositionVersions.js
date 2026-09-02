import { computed, ref, unref } from 'vue'

import { api } from '@/lib/api.js'
import { auth, can } from '@/lib/auth.js'


export const POSITION_VERSION_STATUS_LABELS = Object.freeze({
  draft: '草稿',
  pending_approval: '待审批',
  published: '已发布',
  superseded: '已取代',
  rejected: '已驳回',
  cancelled: '已取消',
  retired: '已退休',
})

export const POSITION_LIFECYCLE_LABELS = Object.freeze({
  active: '生效中',
  retired: '已退休',
})

export function positionVersionStatusLabel(status) {
  return POSITION_VERSION_STATUS_LABELS[status] || status || '-'
}

export function positionLifecycleLabel(status) {
  return POSITION_LIFECYCLE_LABELS[status] || status || '-'
}

export function positionVersionErrorMessage(error) {
  const actions = {
    refresh_position_version: '数据已被其他操作更新，请刷新岗位版本后重试',
    select_different_approver: '制单人与批准人必须不同，请切换批准账号',
    resolve_position_references: '存在未处置的岗位引用，请先完成影响处置',
    create_new_revision: '当前版本不可修改，请创建新修订版',
  }
  return actions[error?.action] || error?.message || '岗位版本操作失败'
}

function commandKey(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  const token = uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}:${token}`
}

function byId(items, id) {
  return items.find((item) => Number(item.id) === Number(id)) || null
}

export function usePositionVersions({ actor = null } = {}) {
  const activeTab = ref('current')
  const root = ref(null)
  const versions = ref([])
  const events = ref([])
  const lifecycleRequests = ref([])
  const selectedVersion = ref(null)
  const impact = ref(null)
  const loading = ref(false)
  const impactLoading = ref(false)
  const commandBusy = ref(false)
  const operationError = ref('')

  const actorValue = computed(() => unref(actor) || auth.user || {})
  const actorId = computed(() => Number(
    actorValue.value?.id || actorValue.value?.user_id || 0
  ))
  const current = computed(() => {
    const currentId = root.value?.current_effective_version_id
    return byId(versions.value, currentId)
      || versions.value.find((item) => item.status === 'published')
      || null
  })
  const pending = computed(() => versions.value.find(
    (item) => item.status === 'draft' || item.status === 'pending_approval'
  ) || null)
  const history = computed(() => versions.value.filter(
    (item) => item.id !== current.value?.id && item.id !== pending.value?.id
  ))
  const pendingLifecycle = computed(() => lifecycleRequests.value.find(
    (item) => item.status === 'pending'
  ) || null)
  const comparisonBase = computed(() => {
    const selected = selectedVersion.value
    if (!selected) return null
    if (selected.supersedes_version_id) {
      return byId(versions.value, selected.supersedes_version_id)
    }
    return versions.value
      .filter((item) => Number(item.version) < Number(selected.version))
      .sort((a, b) => Number(b.version) - Number(a.version))[0] || null
  })

  function deny(message) {
    operationError.value = message
    return null
  }

  async function runCommand(permission, callback, ownerId = null) {
    if (commandBusy.value) return null
    if (!can(permission)) return deny(`缺少权限：${permission}`)
    if (ownerId != null && Number(ownerId) === actorId.value) {
      return deny('制单人与批准人必须不同')
    }
    commandBusy.value = true
    operationError.value = ''
    try {
      return await callback()
    } catch (error) {
      operationError.value = positionVersionErrorMessage(error)
      throw error
    } finally {
      commandBusy.value = false
    }
  }

  async function loadImpact(versionId = selectedVersion.value?.id) {
    if (!versionId || !can('positions:impact')) {
      impact.value = null
      return null
    }
    impactLoading.value = true
    try {
      const payload = await api.domains.positionVersions.getPositionVersionImpact(versionId)
      impact.value = payload.impact || payload
      return impact.value
    } catch (error) {
      impact.value = null
      operationError.value = positionVersionErrorMessage(error)
      return null
    } finally {
      impactLoading.value = false
    }
  }

  function versionForTab(tab) {
    if (tab === 'pending') return pending.value
    if (tab === 'history') return history.value[0] || null
    return current.value || pending.value || versions.value[0] || null
  }

  async function selectVersion(versionOrId) {
    selectedVersion.value = typeof versionOrId === 'object'
      ? versionOrId
      : byId(versions.value, versionOrId)
    if (activeTab.value === 'impact') await loadImpact()
    return selectedVersion.value
  }

  async function setActiveTab(tab) {
    if (!['current', 'pending', 'history', 'impact'].includes(tab)) return null
    activeTab.value = tab
    if (tab !== 'impact') selectedVersion.value = versionForTab(tab)
    if (tab === 'impact') await loadImpact()
    return selectedVersion.value
  }

  async function loadPosition(positionId, preferredVersionId = null) {
    loading.value = true
    operationError.value = ''
    try {
      const [detail, requests] = await Promise.all([
        api.domains.positionVersions.listPositionVersions(positionId),
        api.domains.positionVersions.listPositionLifecycleRequests(positionId),
      ])
      root.value = detail.position || null
      versions.value = [...(detail.versions || [])].sort(
        (a, b) => Number(b.version) - Number(a.version)
      )
      events.value = detail.events || []
      lifecycleRequests.value = Array.isArray(requests) ? requests : (requests.items || [])
      selectedVersion.value = byId(versions.value, preferredVersionId)
        || versionForTab(activeTab.value)
      if (activeTab.value === 'impact') await loadImpact()
      return detail
    } catch (error) {
      operationError.value = positionVersionErrorMessage(error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function createPosition(form) {
    return runCommand('positions:create', async () => {
      const result = await api.domains.positions.createPosition({
        name: String(form.name || '').trim(),
        description: String(form.description || ''),
        process_ids: [...(form.process_ids || [])].map(Number),
        revision_reason: String(form.revision_reason || '').trim(),
        idempotency_key: commandKey('position-create'),
      })
      root.value = result.root
      activeTab.value = 'pending'
      if (can('positions:history')) {
        await loadPosition(result.root.id, result.version.id)
      } else {
        versions.value = [result.version]
        selectedVersion.value = result.version
      }
      return result
    })
  }

  async function createRevision(form) {
    return runCommand('positions:create', async () => {
      if (!root.value?.id) throw new Error('未选择岗位')
      const result = await api.domains.positionVersions.createPositionRevision(
        root.value.id,
        {
          row_version: Number(root.value.row_version || 0),
          name: String(form.name || '').trim(),
          description: String(form.description || ''),
          process_ids: [...(form.process_ids || [])].map(Number),
          revision_reason: String(form.revision_reason || '').trim(),
          idempotency_key: commandKey('position-revision'),
        }
      )
      activeTab.value = 'pending'
      await loadPosition(root.value.id, result.id)
      return result
    })
  }

  async function updateSelected(form) {
    return runCommand('positions:create', async () => {
      const version = selectedVersion.value
      if (!version || version.status !== 'draft') throw new Error('仅草稿版本允许编辑')
      const result = await api.domains.positionVersions.updatePositionVersion(
        version.id,
        {
          row_version: Number(version.row_version || 0),
          name: String(form.name || '').trim(),
          description: String(form.description || ''),
          process_ids: [...(form.process_ids || [])].map(Number),
          idempotency_key: commandKey('position-update'),
        }
      )
      await loadPosition(version.position_id, result.id)
      return result
    })
  }

  async function transitionSelected(action, reason = '') {
    const permission = {
      submit: 'positions:submit',
      approve: 'positions:approve',
      reject: 'positions:reject',
      cancel: 'positions:submit',
    }[action]
    const version = selectedVersion.value
    const separationOwner = ['approve', 'reject'].includes(action)
      ? version?.created_by
      : null
    return runCommand(permission, async () => {
      if (!version) throw new Error('未选择岗位版本')
      const payload = {
        row_version: Number(version.row_version || 0),
        idempotency_key: commandKey(`position-${action}`),
      }
      if (['reject', 'cancel'].includes(action)) payload.reason = String(reason || '').trim()
      const method = {
        submit: 'submitPositionVersion',
        approve: 'approvePositionVersion',
        reject: 'rejectPositionVersion',
        cancel: 'cancelPositionVersion',
      }[action]
      const result = await api.domains.positionVersions[method](version.id, payload)
      await loadPosition(version.position_id, result.id)
      return result
    }, separationOwner)
  }

  const submitSelected = () => transitionSelected('submit')
  const approveSelected = () => transitionSelected('approve')
  const rejectSelected = (reason) => transitionSelected('reject', reason)
  const cancelSelected = (reason) => transitionSelected('cancel', reason)

  async function requestLifecycle(action, reason) {
    const permission = action === 'retire' ? 'positions:retire' : 'positions:reactivate'
    return runCommand(permission, async () => {
      if (!root.value?.id) throw new Error('未选择岗位')
      const method = action === 'retire'
        ? 'requestPositionRetirement'
        : 'requestPositionReactivation'
      const result = await api.domains.positionVersions[method](root.value.id, {
        row_version: Number(root.value.row_version || 0),
        lifecycle_reason: String(reason || '').trim(),
        idempotency_key: commandKey(`position-${action}`),
      })
      activeTab.value = 'pending'
      await loadPosition(root.value.id, selectedVersion.value?.id)
      return result
    })
  }

  async function resolveLifecycle(action, requestItem, reason = '') {
    const permission = action === 'approve' ? 'positions:approve' : 'positions:reject'
    return runCommand(permission, async () => {
      if (!requestItem) throw new Error('未选择生命周期申请')
      const payload = {
        row_version: Number(requestItem.row_version || 0),
        idempotency_key: commandKey(`position-lifecycle-${action}`),
      }
      if (action === 'reject') payload.reason = String(reason || '').trim()
      const method = action === 'approve'
        ? 'approvePositionLifecycle'
        : 'rejectPositionLifecycle'
      const result = await api.domains.positionVersions[method](requestItem.id, payload)
      await loadPosition(requestItem.position_id, selectedVersion.value?.id)
      return result
    }, requestItem?.requested_by)
  }

  function reset() {
    activeTab.value = 'current'
    root.value = null
    versions.value = []
    events.value = []
    lifecycleRequests.value = []
    selectedVersion.value = null
    impact.value = null
    operationError.value = ''
  }

  return {
    activeTab,
    root,
    versions,
    events,
    lifecycleRequests,
    selectedVersion,
    current,
    pending,
    history,
    pendingLifecycle,
    comparisonBase,
    impact,
    loading,
    impactLoading,
    commandBusy,
    operationError,
    actorId,
    loadPosition,
    loadImpact,
    selectVersion,
    setActiveTab,
    createPosition,
    createRevision,
    updateSelected,
    submitSelected,
    approveSelected,
    rejectSelected,
    cancelSelected,
    requestRetirement: (reason) => requestLifecycle('retire', reason),
    requestReactivation: (reason) => requestLifecycle('reactivate', reason),
    approveLifecycle: (requestItem) => resolveLifecycle('approve', requestItem),
    rejectLifecycle: (requestItem, reason) => resolveLifecycle('reject', requestItem, reason),
    reset,
  }
}
