import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { auth, can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const MAX_RECEIPT_BYTES = 2 * 1024 * 1024
const PENDING_KEYS_STORAGE_PREFIX = 'payroll-settlement:pending-idempotency-keys:'

function makeIdempotencyKey(action) {
  return `payroll-settlement-ui:${action}:${Date.now()}:${Math.random().toString(16).slice(2)}`
}

function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export function settlementStatusLabel(status) {
  return {
    not_exported: '待生成支付清单',
    exported: '待上传支付回执',
    receipting: '待运行对账',
    difference_pending: '差异待处理',
    reconciled: '对账通过',
    closed: '已结账锁定',
  }[status] || '未知状态'
}

export function differenceTypeLabel(type) {
  return {
    missing_receipt: '缺少支付回执',
    failed_payment: '支付失败',
    underpaid: '支付不足',
    overpaid: '支付超额',
    duplicate_success: '重复成功回执',
    employee_mismatch: '员工信息不匹配',
    unknown_reference: '未知支付引用',
    invalid_amount: '无效金额',
  }[type] || type || '未知差异'
}

function readPendingIdempotencyKeys(storageKey) {
  try {
    const entries = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
    return new Map(Object.entries(entries).filter(([, value]) => typeof value === 'string'))
  } catch (_) {
    return new Map()
  }
}

export function usePayrollSettlement() {
  const storageKey = `${PENDING_KEYS_STORAGE_PREFIX}${auth.user?.id || 'anonymous'}`
  const pendingIdempotencyKeys = readPendingIdempotencyKeys(storageKey)
  let settlementLoadSequence = 0
  const month = ref(currentMonth())
  const batches = ref([])
  const selectedBatchId = ref(null)
  const settlement = ref(null)
  const loading = ref(false)
  const detailLoading = ref(false)
  const working = ref(false)
  const receiptFile = ref(null)
  const resolutionReasons = ref({})
  const differenceTypeFilter = ref('all')
  const blockingFilter = ref('all')
  const employeeFilter = ref('')

  const availableBatches = computed(() => batches.value.filter(batch => (
    batch.status === 'confirmed' && !batch.superseded_by_batch_id
    && Number(batch.negative_payable_count || 0) === 0
  )))
  const selectedBatch = computed(() => availableBatches.value.find(
    batch => batch.id === selectedBatchId.value,
  ) || null)
  const currentExport = computed(() => settlement.value?.current_export || null)
  const exportVersions = computed(() => settlement.value?.exports || [])
  const receiptBatches = computed(() => settlement.value?.receipt_batches || [])
  const latestReconciliation = computed(() => settlement.value?.latest_reconciliation || null)
  const reconciliationItems = computed(() => latestReconciliation.value?.items || [])
  const differenceTypes = computed(() => [...new Set(
    reconciliationItems.value.map(item => item.difference_type).filter(Boolean),
  )])
  const filteredDifferences = computed(() => {
    const employeeQuery = employeeFilter.value.trim().toLocaleLowerCase()
    return reconciliationItems.value.filter(item => {
      if (differenceTypeFilter.value !== 'all'
        && item.difference_type !== differenceTypeFilter.value) return false
      if (blockingFilter.value !== 'all'
        && Boolean(item.blocking) !== (blockingFilter.value === 'blocking')) return false
      if (!employeeQuery) return true
      const detail = detailForDifference(item)
      const identity = [
        item.employee_no_snapshot, item.employee_name_snapshot,
        detail.employee_no, detail.employee_name,
      ].filter(Boolean).join(' ').toLocaleLowerCase()
      return identity.includes(employeeQuery)
    })
  })
  const canView = computed(() => can('wages:view_all') || can('wages:prepare') || can('wages:approve'))
  const canExport = computed(() => can('wages:export'))
  const canReceipt = computed(() => can('wages:receipt'))
  const canReconcile = computed(() => can('wages:reconcile'))
  const canClosePermission = computed(() => can('wages:close'))
  const isClosed = computed(() => settlement.value?.status === 'closed')
  const canCreateExport = computed(() => Boolean(
    selectedBatch.value && Number(selectedBatch.value.negative_payable_count || 0) === 0
    && canExport.value && !isClosed.value && receiptBatches.value.length === 0
  ))
  const canUploadReceipt = computed(() => Boolean(
    currentExport.value && canReceipt.value && !isClosed.value
  ))
  const canRunReconciliation = computed(() => Boolean(
    settlement.value?.id && currentExport.value && receiptBatches.value.length
    && canReconcile.value && !isClosed.value
  ))
  const canClose = computed(() => Boolean(
    settlement.value?.can_close && canClosePermission.value && !isClosed.value
  ))
  const closeSummary = computed(() => ({
    finalAmount: money(settlement.value?.successful_paid_cents),
    exportVersion: currentExport.value?.export_version || '-',
    receiptBatchCount: receiptBatches.value.length,
    reconciliationVersion: latestReconciliation.value?.run_version || '-',
  }))

  function money(cents) {
    return `¥${(Number(cents || 0) / 100).toFixed(2)}`
  }

  function idempotencyKey(action, scope) {
    const operation = `${action}:${scope}`
    if (!pendingIdempotencyKeys.has(operation)) {
      pendingIdempotencyKeys.set(operation, makeIdempotencyKey(action))
      persistPendingIdempotencyKeys()
    }
    return pendingIdempotencyKeys.get(operation)
  }

  function persistPendingIdempotencyKeys() {
    try {
      if (pendingIdempotencyKeys.size) {
        sessionStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(pendingIdempotencyKeys)))
      } else {
        sessionStorage.removeItem(storageKey)
      }
    } catch (_) {
      // Keep the in-memory fallback if browser storage is unavailable.
    }
  }

  function clearPendingIdempotencyKey(action, scope) {
    pendingIdempotencyKeys.delete(`${action}:${scope}`)
    persistPendingIdempotencyKeys()
  }

  function clearPendingIdempotencyKeys(action, scopePrefix) {
    const prefix = `${action}:${scopePrefix}`
    for (const operation of pendingIdempotencyKeys.keys()) {
      if (operation.startsWith(prefix)) pendingIdempotencyKeys.delete(operation)
    }
    persistPendingIdempotencyKeys()
  }

  async function loadSettlement(batchId = selectedBatchId.value) {
    const requestSequence = ++settlementLoadSequence
    if (!batchId) {
      settlement.value = null
      detailLoading.value = false
      return
    }
    detailLoading.value = true
    try {
      const result = await api.domains.wages.getPayrollSettlement(batchId)
      if (requestSequence !== settlementLoadSequence || batchId !== selectedBatchId.value) return
      settlement.value = result
      resolutionReasons.value = {}
    } catch (error) {
      showToast(error.message || '结算信息加载失败', 'error')
    } finally {
      if (requestSequence === settlementLoadSequence) detailLoading.value = false
    }
  }

  async function load() {
    if (!canView.value) {
      batches.value = []
      selectedBatchId.value = null
      settlement.value = null
      return
    }
    loading.value = true
    try {
      const result = await api.domains.wages.listPayrollBatches({
        payroll_month: month.value,
        status: 'confirmed',
      })
      batches.value = result.batches || []
      const stillAvailable = availableBatches.value.some(
        batch => batch.id === selectedBatchId.value,
      )
      if (!stillAvailable) selectedBatchId.value = availableBatches.value[0]?.id || null
      await loadSettlement()
    } catch (error) {
      showToast(error.message || '工资批次加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  function selectBatch(batch) {
    selectedBatchId.value = batch.id
    return loadSettlement(batch.id)
  }

  function setReceiptFile(file) {
    if (file && file.size > MAX_RECEIPT_BYTES) {
      receiptFile.value = null
      showToast('回执 CSV 不能超过 2 MB', 'error')
      return
    }
    receiptFile.value = file || null
  }

  async function runAction(action, successMessage, completedOperation, afterSuccess) {
    working.value = true
    try {
      const result = await action()
      showToast(successMessage(result))
      if (completedOperation) {
        clearPendingIdempotencyKey(completedOperation.action, completedOperation.scope)
      }
      afterSuccess?.(result)
      await loadSettlement(selectedBatchId.value)
      return result
    } catch (error) {
      showToast(error.message || '结算操作失败', 'error')
      return null
    } finally {
      working.value = false
    }
  }

  function createExport() {
    if (!selectedBatch.value) return Promise.resolve(null)
    const batchId = selectedBatch.value.id
    const key = idempotencyKey('export', batchId)
    return runAction(
      () => api.domains.wages.createPayrollSettlementExport(batchId, {
        idempotency_key: key,
      }),
      result => result?.replayed ? '支付清单已存在' : '正式支付清单已生成',
      { action: 'export', scope: batchId },
    )
  }

  function uploadReceipt() {
    if (!currentExport.value || !receiptFile.value) {
      showToast('请选择支付回执 CSV 文件', 'error')
      return Promise.resolve(null)
    }
    const fileScope = [
      currentExport.value.id,
      receiptFile.value.name,
      receiptFile.value.size,
      receiptFile.value.lastModified,
    ].join(':')
    const key = idempotencyKey('receipt', fileScope)
    const settlementId = settlement.value.id
    const exportId = currentExport.value.id
    const formData = new FormData()
    formData.append('file', receiptFile.value)
    formData.append('idempotency_key', key)
    return runAction(
      () => api.domains.wages.uploadPayrollSettlementReceipt(exportId, formData),
      result => result?.replayed ? '该回执已导入' : '支付回执已导入',
      { action: 'receipt', scope: fileScope },
      () => clearPendingIdempotencyKeys('reconcile', `${settlementId}:${exportId}:`),
    ).then(result => {
      if (result) receiptFile.value = null
      return result
    })
  }

  function reconcile() {
    if (!settlement.value?.id) return Promise.resolve(null)
    const reconciliationScope = [
      settlement.value.id,
      currentExport.value?.id || '',
      receiptBatches.value.map(receipt => receipt.id).join(','),
    ].join(':')
    const key = idempotencyKey('reconcile', reconciliationScope)
    return runAction(
      () => api.domains.wages.reconcilePayrollSettlement(
        settlement.value.id,
        { idempotency_key: key },
      ),
      result => result?.status === 'reconciled'
        ? '对账通过，应付与成功支付一致'
        : `对账完成，发现 ${Number(result?.blocking_count || 0)} 项待处理差异`,
      { action: 'reconcile', scope: reconciliationScope },
    )
  }

  function detailForDifference(item) {
    try {
      return JSON.parse(item.detail_json || '{}')
    } catch (_) {
      return {}
    }
  }

  function resolutionCode(item) {
    const detail = detailForDifference(item)
    if (item.difference_type === 'duplicate_success') return 'exclude_duplicate'
    if (item.difference_type === 'unknown_reference') return 'exclude_unknown_reference'
    if (item.difference_type === 'employee_mismatch' && !detail.employee_no_mismatch) {
      return 'accept_name_mismatch'
    }
    return ''
  }

  function canResolveDifference(item) {
    return Boolean(canReconcile.value && !isClosed.value && resolutionCode(item))
  }

  function resolveDifference(item, reason) {
    const resolutionReason = String(reason || '').trim()
    if (!resolutionCode(item) || !resolutionReason) {
      showToast('请填写处理原因，并确认该差异支持人工处理', 'error')
      return Promise.resolve(null)
    }
    const detail = detailForDifference(item)
    const code = resolutionCode(item)
    const settlementId = settlement.value.id
    const exportId = currentExport.value.id
    const scope = [item.id, code, detail.receipt_item_id || '', resolutionReason].join(':')
    const key = idempotencyKey('difference', scope)
    return runAction(
      () => api.domains.wages.resolvePayrollSettlementDifference(item.id, {
        resolution_code: code,
        resolution_reason: resolutionReason,
        receipt_item_id: detail.receipt_item_id,
        idempotency_key: key,
      }),
      () => '差异处理已记录，请重新运行对账',
      { action: 'difference', scope },
      () => clearPendingIdempotencyKeys(
        'reconcile', `${settlementId}:${exportId}:`,
      ),
    )
  }

  function closeSettlement() {
    if (!canClose.value) return Promise.resolve(null)
    const summary = closeSummary.value
    if (!window.confirm([
      '确认结账并锁定本次工资结算？',
      `最终金额：${summary.finalAmount}`,
      `当前导出版本：V${summary.exportVersion}`,
      `回执批次数量：${summary.receiptBatchCount}`,
      `对账运行版本：第 ${summary.reconciliationVersion} 次`,
      '结账后不能继续上传回执或处理差异。',
    ].join('\n'))) {
      return Promise.resolve(null)
    }
    const reason = window.prompt('请填写结账说明')?.trim()
    if (!reason) return Promise.resolve(null)
    const scope = [settlement.value.id, settlement.value.row_version, reason].join(':')
    const key = idempotencyKey('close', scope)
    return runAction(
      () => api.domains.wages.closePayrollSettlement(settlement.value.id, {
        row_version: settlement.value.row_version,
        close_reason: reason,
        idempotency_key: key,
      }),
      () => '工资结算已结账锁定',
      { action: 'close', scope },
    )
  }

  function downloadUrl(exportId) {
    return api.domains.wages.payrollSettlementExportDownloadUrl(exportId)
  }

  onMounted(() => {
    if (canView.value) load()
  })

  return {
    month,
    availableBatches,
    selectedBatch,
    selectedBatchId,
    settlement,
    currentExport,
    exportVersions,
    receiptBatches,
    latestReconciliation,
    differenceTypes,
    filteredDifferences,
    differenceTypeFilter,
    blockingFilter,
    employeeFilter,
    closeSummary,
    loading,
    detailLoading,
    working,
    receiptFile,
    resolutionReasons,
    canExport,
    canReconcile,
    canUploadReceipt,
    canCreateExport,
    canRunReconciliation,
    canClose,
    money,
    load,
    selectBatch,
    setReceiptFile,
    createExport,
    uploadReceipt,
    reconcile,
    differenceFor: detailForDifference,
    differenceTypeLabel,
    canResolveDifference,
    resolveDifference,
    closeSettlement,
    downloadUrl,
  }
}
