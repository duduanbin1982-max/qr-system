import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'


export const PROCESS_VERSION_STATUS_LABELS = Object.freeze({
  draft: '草稿',
  pending_approval: '待审批',
  published: '已发布',
  rejected: '已驳回',
  superseded: '已取代',
  retired: '已退休',
})

export const PROCESS_LIFECYCLE_LABELS = Object.freeze({
  active: '生效中',
  retirement_pending: '退休审批中',
  retired: '已退休',
  reactivation_pending: '重新启用审批中',
})

export function processVersionStatusLabel(status) {
  return PROCESS_VERSION_STATUS_LABELS[status] || status || '-'
}

export function processLifecycleLabel(status) {
  return PROCESS_LIFECYCLE_LABELS[status] || status || '-'
}

function commandKey(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  const token = uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}:${token}`
}

export function processVersionErrorMessage(error) {
  const actions = {
    refresh_process_version: '数据已被其他操作更新，请刷新版本详情后重试',
    select_different_approver: '制单人与批准人必须不同，请切换批准账号',
    resolve_release_dependencies: '存在未处理的路线或工价依赖，请先完成影响处置',
    create_new_revision: '当前版本不可修改，请创建新的修订版',
  }
  return actions[error?.action] || error?.message || '版本操作失败'
}

function versionById(versions, versionId) {
  return versions.find((item) => Number(item.id) === Number(versionId)) || null
}

export function useProcessVersions() {
  const selectedProcess = ref(null)
  const root = ref(null)
  const versions = ref([])
  const events = ref([])
  const selectedVersion = ref(null)
  const impact = ref(null)
  const loadingDetail = ref(false)
  const loadingImpact = ref(false)
  const impactError = ref('')
  const busy = ref(false)
  const operationError = ref('')

  const currentVersion = computed(() => {
    const currentId = root.value?.current_effective_version_id
    return versionById(versions.value, currentId)
      || versions.value.find((item) => item.status === 'published')
      || null
  })

  const openVersion = computed(() => versions.value.find(
    (item) => item.status === 'draft' || item.status === 'pending_approval'
  ) || null)

  const historicalVersions = computed(() => versions.value.filter(
    (item) => item.id !== currentVersion.value?.id && item.id !== openVersion.value?.id
  ))

  const comparisonBase = computed(() => {
    const selected = selectedVersion.value
    if (!selected) return null
    if (selected.supersedes_version_id) {
      return versionById(versions.value, selected.supersedes_version_id)
    }
    return versions.value
      .filter((item) => Number(item.version) < Number(selected.version))
      .sort((a, b) => Number(b.version) - Number(a.version))[0] || null
  })

  const totalReferences = computed(() => Number(impact.value?.total_references || 0))

  async function loadImpact(versionId) {
    if (!versionId) {
      impact.value = null
      impactError.value = ''
      return null
    }
    loadingImpact.value = true
    impactError.value = ''
    try {
      const payload = await api.domains.processVersions.getProcessVersionImpact(versionId)
      impact.value = payload.impact || payload
      return impact.value
    } catch (error) {
      impact.value = null
      impactError.value = processVersionErrorMessage(error)
      return null
    } finally {
      loadingImpact.value = false
    }
  }

  async function selectVersion(versionOrId) {
    const version = typeof versionOrId === 'object'
      ? versionOrId
      : versionById(versions.value, versionOrId)
    selectedVersion.value = version || null
    await loadImpact(version?.id)
    return selectedVersion.value
  }

  async function loadProcess(processId, preferredVersionId = null) {
    loadingDetail.value = true
    operationError.value = ''
    try {
      const payload = await api.domains.processVersions.listProcessVersions(processId)
      root.value = payload.process || null
      versions.value = [...(payload.versions || [])].sort(
        (a, b) => Number(b.version) - Number(a.version)
      )
      events.value = payload.events || []
      selectedProcess.value = {
        ...(selectedProcess.value || {}),
        ...(root.value || {}),
        id: root.value?.id || processId,
      }
      const preferred = versionById(versions.value, preferredVersionId)
      await selectVersion(preferred || openVersion.value || currentVersion.value || versions.value[0])
      return payload
    } catch (error) {
      operationError.value = processVersionErrorMessage(error)
      throw error
    } finally {
      loadingDetail.value = false
    }
  }

  async function openProcess(process) {
    selectedProcess.value = process ? { ...process } : null
    if (!process?.id) return null
    return loadProcess(process.id, process.process_version_id)
  }

  async function runOperation(callback) {
    if (busy.value) return null
    busy.value = true
    operationError.value = ''
    try {
      return await callback()
    } catch (error) {
      operationError.value = processVersionErrorMessage(error)
      throw error
    } finally {
      busy.value = false
    }
  }

  async function createProcess(form) {
    return runOperation(async () => {
      const result = await api.domains.processVersions.createVersionedProcess({
        name: String(form.name || '').trim(),
        category: form.category,
        description: String(form.description || ''),
        seq_order: Number(form.seq_order || 0),
        revision_reason: String(form.revision_reason || '').trim(),
        idempotency_key: commandKey('process-create'),
      })
      selectedProcess.value = result.root
      await loadProcess(result.root.id, result.version.id)
      return result
    })
  }

  async function createRevision(form) {
    return runOperation(async () => {
      const processId = root.value?.id || selectedProcess.value?.id
      if (!processId) throw new Error('未选择工序')
      const result = await api.domains.processVersions.createProcessRevision(processId, {
        row_version: Number(root.value?.row_version || 0),
        revision_reason: String(form.revision_reason || '').trim(),
        idempotency_key: commandKey('process-revision'),
        name: String(form.name || '').trim(),
        category: form.category,
        description: String(form.description || ''),
        seq_order: Number(form.seq_order || 0),
      })
      await loadProcess(processId, result.id)
      return result
    })
  }

  async function updateDraft(form) {
    return runOperation(async () => {
      const version = selectedVersion.value
      if (!version || version.status !== 'draft') throw new Error('仅草稿版本允许编辑')
      const result = await api.domains.processVersions.updateProcessVersion(version.id, {
        row_version: Number(version.row_version || 0),
        name: String(form.name || '').trim(),
        category: form.category,
        description: String(form.description || ''),
        seq_order: Number(form.seq_order || 0),
      })
      await loadProcess(version.process_id, result.id)
      return result
    })
  }

  async function transition(action, reason = '') {
    return runOperation(async () => {
      const version = selectedVersion.value
      if (!version) throw new Error('未选择工序版本')
      const payload = {
        row_version: Number(version.row_version || 0),
        idempotency_key: commandKey(`process-${action}`),
      }
      if (action === 'reject') payload.reason = String(reason || '').trim()
      const methods = {
        submit: 'submitProcessVersion',
        approve: 'approveProcessVersion',
        reject: 'rejectProcessVersion',
      }
      const method = methods[action]
      if (!method) throw new Error('不支持的版本操作')
      const result = await api.domains.processVersions[method](version.id, payload)
      await loadProcess(version.process_id, result.id)
      return result
    })
  }

  async function requestLifecycle(action, reason) {
    return runOperation(async () => {
      const processId = root.value?.id || selectedProcess.value?.id
      if (!processId) throw new Error('未选择工序')
      const payload = {
        row_version: Number(root.value?.row_version || 0),
        reason: String(reason || '').trim(),
        idempotency_key: commandKey(`process-${action}`),
      }
      const method = action === 'retire'
        ? 'requestProcessRetirement'
        : 'requestProcessReactivation'
      const result = await api.domains.processVersions[method](processId, payload)
      await loadProcess(processId, selectedVersion.value?.id)
      return result
    })
  }

  function reset() {
    selectedProcess.value = null
    root.value = null
    versions.value = []
    events.value = []
    selectedVersion.value = null
    impact.value = null
    impactError.value = ''
    operationError.value = ''
  }

  return {
    selectedProcess,
    root,
    versions,
    events,
    selectedVersion,
    currentVersion,
    openVersion,
    historicalVersions,
    comparisonBase,
    impact,
    totalReferences,
    loadingDetail,
    loadingImpact,
    impactError,
    busy,
    operationError,
    openProcess,
    loadProcess,
    selectVersion,
    createProcess,
    createRevision,
    updateDraft,
    transition,
    requestLifecycle,
    reset,
  }
}
