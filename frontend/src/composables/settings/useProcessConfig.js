import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { api } from '@/lib/api.js'
import { auth, can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export const PROCESS_CONFIG_FIELDS = Object.freeze([
  'process_order_mode',
  'serial_process_report_mode',
  'limit_by_prev_process',
  'limit_by_order_qty',
  'approval_enabled',
])

export const PROCESS_CONFIG_DEFAULTS = Object.freeze({
  process_order_mode: 'sequential',
  serial_process_report_mode: 'strict',
  limit_by_prev_process: 1,
  limit_by_order_qty: 1,
  approval_enabled: 1,
})

export const PROCESS_CONFIG_STATUS_LABELS = Object.freeze({
  draft: '草稿',
  pending_approval: '待审批',
  published: '已发布',
  rejected: '已驳回',
})

export function processConfigStatusLabel(status) {
  return PROCESS_CONFIG_STATUS_LABELS[status] || status || '-'
}

function commandKey(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  const token = uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}:${token}`
}

function numericFlag(value, fallback) {
  return [1, true, '1'].includes(value) ? 1
    : [0, false, '0'].includes(value) ? 0
      : fallback
}

function valuesFrom(source) {
  const input = source || {}
  return {
    process_order_mode: input.process_order_mode || PROCESS_CONFIG_DEFAULTS.process_order_mode,
    serial_process_report_mode: input.serial_process_report_mode || PROCESS_CONFIG_DEFAULTS.serial_process_report_mode,
    limit_by_prev_process: numericFlag(input.limit_by_prev_process, PROCESS_CONFIG_DEFAULTS.limit_by_prev_process),
    limit_by_order_qty: numericFlag(input.limit_by_order_qty, PROCESS_CONFIG_DEFAULTS.limit_by_order_qty),
    approval_enabled: numericFlag(input.approval_enabled, PROCESS_CONFIG_DEFAULTS.approval_enabled),
  }
}

function actorId() {
  return Number(auth.user?.id || auth.user?.user_id || 0)
}

export function processConfigErrorMessage(error) {
  const actions = {
    reload_process_config: '工艺配置已被其他用户更新，已刷新当前版本，请重新核对',
    select_different_approver: '制单人与批准人必须不同，请切换批准账号',
    review_open_process_config_revision: '已有未完成修订版，请先处理当前草稿或待审批版本',
    use_process_config_api: '工艺配置必须通过版本化页面提交',
  }
  return actions[error?.action] || error?.message || '工艺配置操作失败'
}

export function useProcessConfig() {
  const config = ref(null)
  const openRevision = ref(null)
  const revisions = ref([])
  const form = reactive(valuesFrom())
  const revisionReason = ref('')
  const loading = ref(true)
  const historyLoading = ref(false)
  const busy = ref(false)
  const operationError = ref('')
  const conflict = ref(false)

  const canCreate = computed(() => can('process_config:create'))
  const canSubmit = computed(() => can('process_config:submit'))
  const canApprove = computed(() => can('process_config:approve'))
  const canReject = computed(() => can('process_config:reject'))
  const canHistory = computed(() => can('process_config:history'))
  const current = computed(() => config.value || {})
  const draft = computed(() => openRevision.value?.status === 'draft' ? openRevision.value : null)
  const pending = computed(() => openRevision.value?.status === 'pending_approval' ? openRevision.value : null)
  const isDraftOwner = computed(() => Number(draft.value?.created_by || 0) === actorId())
  const canEditDraft = computed(() => canCreate.value && (!openRevision.value || isDraftOwner.value) && !pending.value)
  const configValuesDirty = computed(() => {
    const base = openRevision.value ? valuesFrom(openRevision.value) : valuesFrom(config.value)
    return PROCESS_CONFIG_FIELDS.some(field => form[field] !== base[field])
  })
  const processConfigDirty = computed(() => {
    const reasonChanged = Boolean(revisionReason.value.trim())
      && revisionReason.value.trim() !== String(openRevision.value?.revision_reason || '').trim()
    return configValuesDirty.value || reasonChanged
  })

  function applySource() {
    Object.assign(form, valuesFrom(openRevision.value || config.value))
    revisionReason.value = openRevision.value
      ? String(openRevision.value.revision_reason || '')
      : ''
    conflict.value = false
  }

  async function loadHistory() {
    if (!canHistory.value) return
    historyLoading.value = true
    try {
      const payload = await api.domains.settings.getProcessConfigHistory(100)
      revisions.value = payload.revisions || []
    } catch (error) {
      operationError.value = processConfigErrorMessage(error)
    } finally {
      historyLoading.value = false
    }
  }

  async function loadProcessConfig() {
    loading.value = true
    operationError.value = ''
    try {
      const payload = await api.domains.settings.getProcessConfig()
      config.value = payload.config || null
      openRevision.value = payload.open_revision || null
      applySource()
      await loadHistory()
      return payload
    } catch (error) {
      operationError.value = processConfigErrorMessage(error)
      showToast(operationError.value, 'error')
      throw error
    } finally {
      loading.value = false
    }
  }

  async function runOperation(operation) {
    if (busy.value) return null
    busy.value = true
    operationError.value = ''
    try {
      const result = await operation()
      await loadProcessConfig()
      return result
    } catch (error) {
      const message = processConfigErrorMessage(error)
      const isConflict = Number(error?.status || error?.code) === 409
      if (isConflict) {
        try { await loadProcessConfig() } catch (_) { /* keep the original conflict */ }
      }
      operationError.value = message
      conflict.value = isConflict
      throw error
    } finally {
      busy.value = false
    }
  }

  function commandValues() {
    return Object.fromEntries(PROCESS_CONFIG_FIELDS.map(field => [field, form[field]]))
  }

  async function createRevision() {
    if (!canEditDraft.value) throw new Error('当前工艺配置不可编辑')
    if (!revisionReason.value.trim()) throw new Error('请填写修订原因')
    return runOperation(() => api.domains.settings.createProcessConfigRevision({
      ...commandValues(),
      row_version: Number(config.value?.row_version || 0),
      revision_reason: revisionReason.value.trim(),
      idempotency_key: commandKey('process-config-create'),
    }))
  }

  async function updateDraft() {
    if (!draft.value || !isDraftOwner.value) throw new Error('只有制单人可以修改草稿')
    if (!revisionReason.value.trim()) throw new Error('请填写修订原因')
    return runOperation(() => api.domains.settings.updateProcessConfigRevision(draft.value.id, {
      ...commandValues(),
      row_version: Number(draft.value.row_version || 0),
      revision_reason: revisionReason.value.trim(),
      idempotency_key: commandKey('process-config-update'),
    }))
  }

  async function saveDraft() {
    if (draft.value) return updateDraft()
    return createRevision()
  }

  async function submitRevision() {
    if (!draft.value || !isDraftOwner.value) throw new Error('只有制单人可以提交草稿')
    return runOperation(() => api.domains.settings.submitProcessConfigRevision(draft.value.id, {
      row_version: Number(draft.value.row_version || 0),
      idempotency_key: commandKey('process-config-submit'),
    }))
  }

  async function approveRevision() {
    if (!pending.value) throw new Error('当前没有待审批修订版')
    return runOperation(() => api.domains.settings.approveProcessConfigRevision(pending.value.id, {
      row_version: Number(pending.value.row_version || 0),
      idempotency_key: commandKey('process-config-approve'),
    }))
  }

  async function rejectRevision(reason) {
    if (!pending.value) throw new Error('当前没有待审批修订版')
    const text = String(reason || '').trim()
    if (!text) throw new Error('请填写驳回原因')
    return runOperation(() => api.domains.settings.rejectProcessConfigRevision(pending.value.id, {
      row_version: Number(pending.value.row_version || 0),
      reason: text,
      idempotency_key: commandKey('process-config-reject'),
    }))
  }

  function discardChanges() {
    applySource()
  }

  function handleBeforeUnload(event) {
    if (!processConfigDirty.value) return
    event.preventDefault()
    event.returnValue = ''
  }

  onMounted(() => {
    window.addEventListener('beforeunload', handleBeforeUnload)
    loadProcessConfig().catch(() => {})
  })
  onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))

  return {
    config, current, openRevision, draft, pending, revisions, form, revisionReason,
    loading, historyLoading, busy, operationError, conflict,
    canCreate, canSubmit, canApprove, canReject, canHistory, canEditDraft,
    isDraftOwner, configValuesDirty, processConfigDirty,
    loadProcessConfig, loadHistory, saveDraft, updateDraft, createRevision,
    submitRevision, approveRevision, rejectRevision, discardChanges,
    processConfigStatusLabel,
    hasUnsavedChanges: () => processConfigDirty.value,
  }
}
