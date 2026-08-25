import { ref } from 'vue'

import { api } from '@/lib/api.js'


export const RELEASE_STATUS_LABELS = Object.freeze({
  draft: '草稿',
  pending_approval: '待审批',
  published: '已发布',
  rejected: '已驳回',
})

export function releaseStatusLabel(status) {
  return RELEASE_STATUS_LABELS[status] || status || '-'
}

function commandKey(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  return `${prefix}:${uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

export function releaseErrorMessage(error) {
  const actions = {
    refresh_release_batch: '发布批次已变化，已刷新完整批次，请重新核对后操作',
    select_different_approver: '批次制单人与批准人必须不同，请切换批准账号',
    resolve_release_dependencies: '发布依赖不完整，请补齐路线修订、工序版本或工价处置',
  }
  return actions[error?.action] || error?.message || '成组发布操作失败'
}

function isConflict(error) {
  return Number(error?.status || error?.code) === 409
    || String(error?.action || '').startsWith('refresh_')
}

export function useMasterDataReleases() {
  const batches = ref([])
  const selectedBatch = ref(null)
  const loading = ref(false)
  const busy = ref(false)
  const operationError = ref('')

  async function loadBatches(status = '') {
    loading.value = true
    operationError.value = ''
    try {
      const payload = await api.domains.masterDataReleases.listReleaseBatches({ status })
      batches.value = payload.batches || payload || []
      return batches.value
    } catch (error) {
      operationError.value = releaseErrorMessage(error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function loadBatch(batchId) {
    const payload = await api.domains.masterDataReleases.getReleaseBatch(batchId)
    selectedBatch.value = payload.batch || payload
    const index = batches.value.findIndex(item => Number(item.id) === Number(batchId))
    if (index >= 0) batches.value.splice(index, 1, selectedBatch.value)
    return selectedBatch.value
  }

  async function runOperation(callback) {
    if (busy.value) return null
    busy.value = true
    operationError.value = ''
    try {
      return await callback()
    } catch (error) {
      operationError.value = releaseErrorMessage(error)
      throw error
    } finally {
      busy.value = false
    }
  }

  async function createBatch(form) {
    return runOperation(async () => {
      const result = await api.domains.masterDataReleases.createReleaseBatch({
        release_no: String(form.release_no || '').trim(),
        revision_reason: String(form.revision_reason || '').trim(),
        process_version_ids: [...new Set((form.process_version_ids || []).map(Number))],
        route_version_ids: [...new Set((form.route_version_ids || []).map(Number))],
        price_version_ids: [...new Set((form.price_version_ids || []).map(Number))],
        idempotency_key: commandKey('release-create'),
      })
      selectedBatch.value = result
      await loadBatches()
      selectedBatch.value = result
      return result
    })
  }

  function requiredProcessIds() {
    const routes = selectedBatch.value?.route_versions || []
    return [...new Set(routes.flatMap(route => (
      route.items || []
    ).map(item => Number(item.process_id))))]
  }

  function validatePriceDispositions(dispositions) {
    const requiredIds = requiredProcessIds()
    const byProcess = new Map((dispositions || []).map(item => [Number(item.process_id), item]))
    const normalized = requiredIds.map(processId => {
      const item = byProcess.get(processId)
      if (!item || !['price_version', 'not_applicable'].includes(item.disposition)) {
        throw new Error('发布前必须完成全部路线节点的工价处置')
      }
      if (item.disposition === 'not_applicable') {
        const reason = String(item.reason || '').trim()
        if (!reason) throw new Error('工价不适用处置必须填写原因')
        return { process_id: processId, disposition: 'not_applicable', reason }
      }
      const priceVersionId = Number(item.price_version_id)
      if (!priceVersionId) throw new Error('工价处置必须选择精确工价版本')
      return { process_id: processId, disposition: 'price_version', price_version_id: priceVersionId }
    })
    return { required_price_process_ids: requiredIds, price_dispositions: normalized }
  }

  async function submitBatch(approvedExceptions = []) {
    return runOperation(async () => {
      const batch = selectedBatch.value
      if (!batch) throw new Error('未选择发布批次')
      const result = await api.domains.masterDataReleases.submitReleaseBatch(batch.id, {
        row_version: Number(batch.row_version || 0),
        approved_exceptions: approvedExceptions,
        idempotency_key: commandKey('release-submit'),
      })
      selectedBatch.value = result
      await loadBatches()
      selectedBatch.value = result
      return result
    })
  }

  async function approveBatch(dispositions) {
    return runOperation(async () => {
      const batch = selectedBatch.value
      if (!batch) throw new Error('未选择发布批次')
      const pricePayload = validatePriceDispositions(dispositions)
      try {
        const result = await api.domains.masterDataReleases.approveReleaseBatch(batch.id, {
          row_version: Number(batch.row_version || 0),
          idempotency_key: commandKey('release-approve'),
          ...pricePayload,
        })
        selectedBatch.value = result
        await loadBatches()
        selectedBatch.value = result
        return result
      } catch (error) {
        if (isConflict(error)) await loadBatch(batch.id)
        throw error
      }
    })
  }

  async function rejectBatch(reason) {
    return runOperation(async () => {
      const batch = selectedBatch.value
      if (!batch) throw new Error('未选择发布批次')
      const result = await api.domains.masterDataReleases.rejectReleaseBatch(batch.id, {
        row_version: Number(batch.row_version || 0),
        reason: String(reason || '').trim(),
        idempotency_key: commandKey('release-reject'),
      })
      selectedBatch.value = result
      await loadBatches()
      selectedBatch.value = result
      return result
    })
  }

  async function removeMember(memberType, memberId, reason) {
    return runOperation(async () => {
      const batch = selectedBatch.value
      if (!batch) throw new Error('未选择发布批次')
      const result = await api.domains.masterDataReleases.removeReleaseBatchMember(
        batch.id,
        {
          member_type: memberType,
          member_id: Number(memberId),
          row_version: Number(batch.row_version || 0),
          reason: String(reason || '').trim(),
          idempotency_key: commandKey('release-member-remove'),
        }
      )
      selectedBatch.value = result
      return result
    })
  }

  async function replaceMember(memberType, memberId, replacementMemberId, reason) {
    return runOperation(async () => {
      const batch = selectedBatch.value
      if (!batch) throw new Error('未选择发布批次')
      const result = await api.domains.masterDataReleases.replaceReleaseBatchMember(
        batch.id,
        {
          member_type: memberType,
          member_id: Number(memberId),
          replacement_member_id: Number(replacementMemberId),
          row_version: Number(batch.row_version || 0),
          reason: String(reason || '').trim(),
          idempotency_key: commandKey('release-member-replace'),
        }
      )
      selectedBatch.value = result
      return result
    })
  }

  return {
    batches,
    selectedBatch,
    loading,
    busy,
    operationError,
    loadBatches,
    loadBatch,
    createBatch,
    submitBatch,
    approveBatch,
    rejectBatch,
    removeMember,
    replaceMember,
    requiredProcessIds,
    validatePriceDispositions,
  }
}
