import { computed, reactive, ref, watch } from 'vue'
import { positionLifecycleLabel, positionVersionErrorMessage, positionVersionStatusLabel, usePositionVersions } from '@/composables/settings/usePositionVersions.js'
import { normalizePositionProcessIds, usePositions } from '@/composables/settings/usePositions.js'
import { showToast } from '@/lib/store.js'

const emptyCreateForm = () => ({ name: '', description: '', revision_reason: '', process_ids: [] })

export function usePositionsWorkspace() {
  const listState = usePositions()
  const versionState = usePositionVersions()
  const { positions, positionTotal, positionLoading, allProcesses, canCreate, canHistory, canImpact, canSubmit, canApprove, canReject, canRetire, canReactivate } = listState
  const { activeTab, root, versions, selectedVersion, current, pending, history, pendingLifecycle, comparisonBase, impact, loading, impactLoading, commandBusy, operationError, actorId } = versionState
  const showCreateModal = ref(false)
  const showDetailModal = ref(false)
  const showRevisionModal = ref(false)
  const showRejectModal = ref(false)
  const showLifecycleModal = ref(false)
  const createForm = reactive(emptyCreateForm())
  const detailForm = reactive({ name: '', description: '', process_ids: [] })
  const revisionReason = ref('')
  const rejectReason = ref('')
  const rejectTarget = ref('version')
  const lifecycleReason = ref('')
  const lifecycleAction = ref('retire')

  const activeCount = computed(() => positions.value.filter((item) => (item.lifecycle_status || 'active') === 'active').length)
  const retiredCount = computed(() => positions.value.filter((item) => item.lifecycle_status === 'retired').length)
  const pendingCount = computed(() => positions.value.filter((item) => item.open_version || item.pending_lifecycle_request).length)
  const versionEditable = computed(() => activeTab.value === 'pending' && selectedVersion.value?.status === 'draft' && canCreate.value)
  const isVersionSelfApproval = computed(() => Number(selectedVersion.value?.created_by || 0) === actorId.value)
  const isLifecycleSelfApproval = computed(() => Number(pendingLifecycle.value?.requested_by || 0) === actorId.value)
  const rejectTitle = computed(() => rejectTarget.value === 'lifecycle' ? '驳回生命周期申请' : (rejectTarget.value === 'cancel' ? '取消岗位修订' : '驳回岗位版本'))
  const processMap = computed(() => new Map(allProcesses.value.map((item) => [Number(item.id), item.process_name || item.name || `#${item.id}`])))

  function enrichVersion(version) {
    if (!version) return null
    const processIds = normalizePositionProcessIds(version)
    return { ...version, process_ids: processIds, processes: processIds.map((processId) => ({ process_id: processId, process_name: processMap.value.get(processId) || `#${processId}` })) }
  }
  const diffBefore = computed(() => enrichVersion(comparisonBase.value))
  const diffAfter = computed(() => enrichVersion(selectedVersion.value))

  watch(selectedVersion, (version) => {
    if (!version) return
    detailForm.name = version.name || ''
    detailForm.description = version.description || ''
    detailForm.process_ids = normalizePositionProcessIds(version)
  }, { immediate: true })

  function lifecycleActionLabel(action) { return action === 'reactivate' ? '重新启用申请' : '退休申请' }
  function toggleProcess(target, processId) { const id = Number(processId); const index = target.indexOf(id); if (index >= 0) target.splice(index, 1); else target.push(id) }
  function validateForm(form, requireReason = false) {
    if (!String(form.name || '').trim()) { showToast('岗位名称不能为空', 'error'); return false }
    if (requireReason && String(form.revision_reason || '').trim().length < 2) { showToast('请填写至少 2 个字符的制单原因', 'error'); return false }
    return true
  }
  function openCreateDialog() { Object.assign(createForm, emptyCreateForm()); showCreateModal.value = true }
  function closeCreateDialog() { if (!commandBusy.value) showCreateModal.value = false }
  async function createPosition() {
    if (!validateForm(createForm, true)) return
    try { await versionState.createPosition(createForm); showCreateModal.value = false; showDetailModal.value = true; await listState.loadPositions(); showToast('V1 草稿已创建') }
    catch (error) { showToast(positionVersionErrorMessage(error), 'error') }
  }
  async function openDetail(position, tab = 'current') {
    showDetailModal.value = true
    try {
      const preferredVersionId = tab === 'pending'
        ? position.open_version?.id
        : position.current_version?.id
      await versionState.setActiveTab(tab)
      await versionState.loadPosition(position.id, preferredVersionId)
      return true
    }
    catch (error) { showToast(positionVersionErrorMessage(error), 'error'); return false }
  }
  function closeDetail() { if (commandBusy.value) return; showDetailModal.value = false; showRevisionModal.value = false; showRejectModal.value = false; showLifecycleModal.value = false; versionState.reset() }
  async function switchTab(tab) { await versionState.setActiveTab(tab) }
  async function selectHistoryVersion(event) { await versionState.selectVersion(Number(event.target.value)) }
  async function selectImpactVersion(event) { await versionState.selectVersion(Number(event.target.value)) }
  function openRevisionDialog() { revisionReason.value = ''; showRevisionModal.value = true }
  async function openRevisionFromRow(position) { if (await openDetail(position, 'current')) openRevisionDialog() }
  async function createRevision() {
    if (revisionReason.value.trim().length < 2) { showToast('请填写至少 2 个字符的修订原因', 'error'); return }
    const base = current.value || selectedVersion.value
    if (!base) return
    try { await versionState.createRevision({ name: base.name, description: base.description, process_ids: normalizePositionProcessIds(base), revision_reason: revisionReason.value }); showRevisionModal.value = false; await listState.loadPositions(); showToast('修订版草稿已创建') }
    catch (error) { showToast(positionVersionErrorMessage(error), 'error') }
  }
  async function saveDraft() {
    if (!validateForm(detailForm)) return
    try { await versionState.updateSelected(detailForm); await listState.loadPositions(); showToast('草稿已保存') }
    catch (error) { showToast(positionVersionErrorMessage(error), 'error') }
  }
  async function submitVersion() { try { await versionState.submitSelected(); await listState.loadPositions(); showToast('版本已提交审批') } catch (error) { showToast(positionVersionErrorMessage(error), 'error') } }
  async function approveVersion() {
    if (!confirm('确认批准并发布该岗位版本？')) return
    try { const result = await versionState.approveSelected(); if (!result) return showToast(operationError.value, 'error'); await listState.loadPositions(); showToast('岗位版本已发布') }
    catch (error) { showToast(positionVersionErrorMessage(error), 'error') }
  }
  function openRejectDialog(target) { rejectTarget.value = target; rejectReason.value = ''; showRejectModal.value = true }
  async function confirmReject() {
    if (rejectReason.value.trim().length < 2) { showToast('请填写至少 2 个字符的原因', 'error'); return }
    try {
      let result
      if (rejectTarget.value === 'lifecycle') result = await versionState.rejectLifecycle(pendingLifecycle.value, rejectReason.value)
      else if (rejectTarget.value === 'cancel') result = await versionState.cancelSelected(rejectReason.value)
      else result = await versionState.rejectSelected(rejectReason.value)
      if (!result) return showToast(operationError.value, 'error')
      showRejectModal.value = false; await listState.loadPositions(); showToast(rejectTarget.value === 'cancel' ? '修订已取消' : '申请已驳回')
    } catch (error) { showToast(positionVersionErrorMessage(error), 'error') }
  }
  function openLifecycleDialog(action) { lifecycleAction.value = action; lifecycleReason.value = ''; showLifecycleModal.value = true }
  async function openLifecycleFromRow(position, action) { if (await openDetail(position, 'current')) openLifecycleDialog(action) }
  async function requestLifecycle() {
    if (lifecycleReason.value.trim().length < 2) { showToast('请填写至少 2 个字符的申请原因', 'error'); return }
    try { const method = lifecycleAction.value === 'retire' ? versionState.requestRetirement : versionState.requestReactivation; await method(lifecycleReason.value); showLifecycleModal.value = false; await listState.loadPositions(); showToast('生命周期申请已提交') }
    catch (error) { showToast(positionVersionErrorMessage(error), 'error') }
  }
  async function approveLifecycle() {
    if (!confirm('确认批准该岗位生命周期申请？')) return
    try { const result = await versionState.approveLifecycle(pendingLifecycle.value); if (!result) return showToast(operationError.value, 'error'); await listState.loadPositions(); showToast('生命周期申请已批准') }
    catch (error) { showToast(positionVersionErrorMessage(error), 'error') }
  }

  return {
    positions, positionTotal, positionLoading, allProcesses, canCreate, canHistory, canImpact, canSubmit, canApprove, canReject, canRetire, canReactivate,
    activeCount, retiredCount, pendingCount, showCreateModal, showDetailModal, showRevisionModal, showRejectModal, showLifecycleModal, createForm, detailForm,
    revisionReason, rejectReason, rejectTarget, rejectTitle, lifecycleReason, lifecycleAction, activeTab, root, versions, selectedVersion, current, pending, history,
    pendingLifecycle, impact, loading, impactLoading, commandBusy, operationError, versionEditable, isVersionSelfApproval, isLifecycleSelfApproval, diffBefore, diffAfter,
    positionLifecycleLabel, positionVersionStatusLabel, lifecycleActionLabel, toggleProcess, openCreateDialog, closeCreateDialog, createPosition, openDetail, closeDetail,
    switchTab, selectHistoryVersion, selectImpactVersion, openRevisionDialog, openRevisionFromRow, createRevision, saveDraft, submitVersion, approveVersion,
    openRejectDialog, confirmReject, openLifecycleDialog, openLifecycleFromRow, requestLifecycle, approveLifecycle,
  }
}
