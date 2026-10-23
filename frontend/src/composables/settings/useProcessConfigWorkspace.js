import { computed, ref } from 'vue'
import { useProcessConfig } from '@/composables/settings/useProcessConfig.js'
import { auth } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function useProcessConfigWorkspace() {
  const state = useProcessConfig()

  const {
    config, current, openRevision, draft, pending, revisions, form, revisionReason,
    loading, historyLoading, busy, operationError,
    canCreate, canSubmit, canApprove, canReject, canEditDraft, isDraftOwner,
    canHistory,
    configValuesDirty, processConfigDirty,
    loadProcessConfig, loadHistory, saveDraft, submitRevision, approveRevision,
    rejectRevision, discardChanges, processConfigStatusLabel,
  } = state

  const rejectReason = ref('')

  const currentUserId = computed(() => Number(auth.user?.id || auth.user?.user_id || 0))

  const canApprovePending = computed(() => Number(pending.value?.created_by || 0) !== currentUserId.value)

  const saveAllowed = computed(() => {
    if (!canEditDraft.value || !revisionReason.value.trim()) return false
    return Boolean(draft.value ? processConfigDirty.value : configValuesDirty.value)
  })

  const FIELD_LABELS = {
    process_order_mode: '报工顺序',
    serial_process_report_mode: '序列号规则',
    limit_by_prev_process: '上道工序上限',
    limit_by_order_qty: '订单数量上限',
    approval_enabled: '报工审批',
  }

  function orderModeLabel(value) {
    return value === 'out_of_order' ? '允许跨工序补报' : '按工艺顺序流转'
  }

  function serialModeLabel(value) {
    return value === 'controlled_backfill' ? '受控跨工序补报' : '严格按当前工序'
  }

  function flagLabel(value) { return [1, true, '1'].includes(value) ? '开启' : '关闭' }

  function changedFields(revision) {
    return (revision.changed_fields || []).map(field => FIELD_LABELS[field] || field).join('、') || '-'
  }

  function selectOrderMode(value) {
    form.process_order_mode = value
    if (value === 'out_of_order') form.limit_by_prev_process = 0
  }

  async function save() {
    const wasDraft = Boolean(draft.value)
    try { await saveDraft(); showToast(wasDraft ? '草稿已保存' : '工艺修订草稿已创建') }
    catch (error) { showToast(error.message || operationError.value || '保存失败', 'error') }
  }

  async function submit() {
    try { await submitRevision(); showToast('工艺修订版已提交审批') }
    catch (error) { showToast(error.message || operationError.value || '提交失败', 'error') }
  }

  async function approve() {
    try { await approveRevision(); showToast('工艺修订版已批准并发布') }
    catch (error) { showToast(error.message || operationError.value || '批准失败', 'error') }
  }

  async function reject() {
    try {
      await rejectRevision(rejectReason.value)
      rejectReason.value = ''
      showToast('工艺修订版已驳回')
    } catch (error) { showToast(error.message || operationError.value || '驳回失败', 'error') }
  }

  function discard() { discardChanges(); rejectReason.value = '' }

  return {
    config,
    current,
    openRevision,
    draft,
    pending,
    revisions,
    form,
    revisionReason,
    loading,
    historyLoading,
    busy,
    operationError,
    canCreate,
    canSubmit,
    canApprove,
    canReject,
    canEditDraft,
    isDraftOwner,
    canHistory,
    configValuesDirty,
    processConfigDirty,
    loadProcessConfig,
    loadHistory,
    saveDraft,
    submitRevision,
    approveRevision,
    rejectRevision,
    discardChanges,
    processConfigStatusLabel,
    rejectReason,
    currentUserId,
    canApprovePending,
    saveAllowed,
    FIELD_LABELS,
    orderModeLabel,
    serialModeLabel,
    flagLabel,
    changedFields,
    selectOrderMode,
    save,
    submit,
    approve,
    reject,
    discard,
    hasUnsavedChanges: state.hasUnsavedChanges
  }
}
