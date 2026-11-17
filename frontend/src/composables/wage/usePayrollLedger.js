import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'
import { navigate } from '@/lib/router.js'

export function usePayrollLedger() {
  const now = new Date()

  const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)

  const status = ref('')

  const allBatches = ref([])

  const batches = computed(() => status.value
    ? allBatches.value.filter(item => item.status === status.value)
    : allBatches.value)

  const loading = ref(false)

  const working = ref(false)

  const selectedId = ref(null)

  const detail = ref(null)

  const sourceDetail = ref(null)

  const sourceLoading = ref(false)

  const sourceLine = ref(null)
  const detailPage = ref(1)
  const detailLimit = ref(50)
  const detailEmployeeQuery = ref('')
  const detailStatusFilter = ref('all')

  let sourceRequestToken = 0
  let detailRequestToken = 0

  const periodControl = ref(null)

  const controlLoading = ref(false)

  const canPrepare = computed(() => can('wages:prepare'))

  const canApprove = computed(() => can('wages:approve'))

  const canExport = computed(() => can('wages:export'))

  const statusOptions = [
    { value:'draft', label:'草稿' }, { value:'exceptions_pending', label:'待异常处理' },
    { value:'review_pending', label:'待复核' }, { value:'locked', label:'已锁定' },
    { value:'confirmed', label:'已确认' }, { value:'voided', label:'已作废' },
  ]

  const pendingExceptions = computed(() => batches.value.reduce(
    (sum, item) => sum + Number(item.exception_count || 0) + Number(item.audit_finding_count || 0), 0
  ))

  const confirmedCount = computed(() => batches.value.filter(item => item.status === 'confirmed').length)

  const monthTotal = computed(() => allBatches.value
    .filter(item => item.status === 'confirmed' && !item.superseded_by_batch_id)
    .reduce((sum, item) => sum + Number(item.payable_wage_cents || 0), 0))

  const filteredDetailLines = computed(() => detail.value?.lines || [])
  const detailTotal = computed(() => Number(detail.value?.lines_total ?? filteredDetailLines.value.length))
  const detailTotalPages = computed(() => Math.max(1, Math.ceil(detailTotal.value / detailLimit.value)))
  const pagedDetailLines = computed(() => filteredDetailLines.value)

  function money(cents) { return `¥${(Number(cents || 0) / 100).toFixed(2)}` }

  function statusLabel(value) { return statusOptions.find(item => item.value === value)?.label || value }

  function editable(batch) { return ['draft', 'exceptions_pending'].includes(batch.status) && !batch.legacy_imported }

  function negativePayableCount(batch) { return Number(batch.negative_payable_count || 0) }

  function hasFormalSettlement(batch) {
    return Boolean(batch.settlement_status && batch.settlement_status !== 'not_exported')
  }

  function primaryAction(batch) {
    if (batch.status === 'draft' && canPrepare.value) {
      if (canSubmit(batch)) return { key: 'submit', label: '提交', disabled: false }
      if (editable(batch)) return { key: 'regenerate', label: '重算', disabled: false }
    }
    if (batch.status === 'exceptions_pending' && (canPrepare.value || canApprove.value)) return { key: 'exceptions', label: '处理异常', disabled: false }
    if (batch.status === 'review_pending' && canApprove.value) return { key: 'lock', label: canLock(batch) ? '锁定' : '先处理负数', disabled: !canLock(batch) }
    if (batch.status === 'locked' && canApprove.value) return { key: 'confirm', label: canConfirm(batch) ? '确认' : '先处理负数', disabled: !canConfirm(batch) }
    if (batch.status === 'confirmed' && canExport.value) return { key: 'settlement', label: '进入结算', disabled: false }
    return { key: 'view', label: '查看', disabled: false }
  }

  function canSubmit(batch) { return batch.status === 'draft' && !batch.exception_count && !batch.audit_finding_count && !batch.legacy_imported && !batch.input_changed && negativePayableCount(batch) === 0 }

  function canLock(batch) { return batch.status === 'review_pending' && negativePayableCount(batch) === 0 }

  function canConfirm(batch) { return batch.status === 'locked' && negativePayableCount(batch) === 0 }

  function canRevise(batch) { return batch.status === 'confirmed' && !batch.superseded_by_batch_id && !hasFormalSettlement(batch) }

  function periodStatusLabel(value) {
    return {
      draft: '草稿',
      exceptions_pending: '待异常处理',
      review_pending: '待复核',
      locked: '已锁定',
      confirmed: '已确认',
      voided: '已作废',
    }[value] || '未生成'
  }

  function idempotency(prefix) { return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}` }

  async function loadControl() {
    const getControl = api.domains.wages.getPayrollPeriodControl
    if (typeof getControl !== 'function') {
      periodControl.value = null
      return
    }
    controlLoading.value = true
    try {
      periodControl.value = await getControl(month.value)
    } catch (error) {
      periodControl.value = null
      showToast(error.message || '工资期间状态加载失败', 'error')
    } finally {
      controlLoading.value = false
    }
  }

  async function load() {
    loading.value = true
    try {
      const data = await api.domains.wages.listPayrollBatches({ payroll_month: month.value })
      allBatches.value = data.batches || []
      await loadControl()
    } catch (error) { showToast(error.message || '工资批次加载失败', 'error') }
    finally { loading.value = false }
  }

  async function createBatch() {
    working.value = true
    try {
      await api.domains.wages.createPayrollBatch({ payroll_month: month.value, idempotency_key: idempotency('payroll-ui') })
      showToast('工资批次已生成')
      await load()
    } catch (error) { showToast(error.message || '生成失败', 'error') }
    finally { working.value = false }
  }

  async function act(call, success) {
    working.value = true
    try { await call(); showToast(success); await load(); if (selectedId.value) await openBatch({ id:selectedId.value }) }
    catch (error) { showToast(error.message || '操作失败', 'error') }
    finally { working.value = false }
  }

  function regenerate(batch) { return act(() => api.domains.wages.regeneratePayrollBatch(batch.id, batch.row_version), '批次已重算') }

  function submit(batch) {
    if (!canSubmit(batch)) {
      const message = batch.input_changed
        ? '输入已变化，请重算后提交'
        : negativePayableCount(batch)
          ? `存在 ${negativePayableCount(batch)} 名员工应付工资为负数，请修正后重算`
          : '当前批次不可提交'
      showToast(message, 'error')
      return
    }
    return act(() => api.domains.wages.submitPayrollBatch(batch.id, batch.row_version), '批次已提交复核')
  }

  function lock(batch) {
    if (!canLock(batch)) {
      showToast(negativePayableCount(batch)
        ? `存在 ${negativePayableCount(batch)} 名员工应付工资为负数，请修正后重算`
        : '当前批次不可锁定', 'error')
      return
    }
    return act(() => api.domains.wages.lockPayrollBatch(batch.id, batch.row_version), '批次已锁定')
  }

  function confirmBatch(batch) {
    if (!canConfirm(batch)) {
      showToast(negativePayableCount(batch)
        ? `存在 ${negativePayableCount(batch)} 名员工应付工资为负数，请修正后重算`
        : '当前批次不可确认', 'error')
      return
    }
    if (!window.confirm(`确认 ${batch.payroll_month} / V${batch.version} 工资批次？`)) return
    return act(() => api.domains.wages.confirmPayrollBatch(batch.id, batch.row_version), '批次已确认')
  }

  function revise(batch) {
    if (!canRevise(batch)) {
      showToast(hasFormalSettlement(batch) ? '该批次已进入财务结算，请在后续期间通过补差或冲销处理' : '当前批次不可修订', 'error')
      return
    }
    const reason = window.prompt('请输入生成修订版的原因')
    if (!reason?.trim()) return
    return act(() => api.domains.wages.revisePayrollBatch(batch.id, { revision_reason:reason.trim(), idempotency_key:idempotency('payroll-revision') }), '修订版已生成')
  }

  async function openBatch(batch) {
    selectedId.value = batch.id
    sourceRequestToken += 1
    sourceDetail.value = null
    sourceLine.value = null
    sourceLoading.value = false
    detailPage.value = 1
    detailEmployeeQuery.value = ''
    detailStatusFilter.value = 'all'
    const requestToken = ++detailRequestToken
    try {
      const result = await api.domains.wages.getPayrollBatch(batch.id, detailParams())
      if (requestToken === detailRequestToken && selectedId.value === batch.id) detail.value = result
    }
    catch (error) { showToast(error.message || '批次明细加载失败', 'error') }
  }

  async function openLineSources(line, page = 1, pinnedCalculationVersion) {
    if (!detail.value?.batch?.id) return
    const batchId = detail.value.batch.id
    const calculationVersion = pinnedCalculationVersion ?? (
      page > 1 ? sourceDetail.value?.calculation_version : undefined
    )
    const requiresPinnedVersion = page > 1 || pinnedCalculationVersion !== undefined
    if (requiresPinnedVersion && calculationVersion === undefined) {
      showToast('请从第一页重新打开来源明细', 'error')
      return
    }
    const requestToken = ++sourceRequestToken
    sourceLine.value = line
    sourceDetail.value = null
    sourceLoading.value = true
    try {
      const params = { page, limit: 50 }
      if (calculationVersion !== undefined) {
        params.calculation_version = calculationVersion
      }
      const result = await api.domains.wages.getPayrollLineSources(
        batchId,
        line.id,
        params,
      )
      if (requestToken === sourceRequestToken && detail.value?.batch?.id === batchId) {
        sourceDetail.value = result
      }
    } catch (error) {
      if (requestToken === sourceRequestToken) {
        showToast(error.message || '工资来源加载失败', 'error')
        if (error.status === 409 && selectedId.value === batchId) {
          await openBatch({ id: batchId })
        }
      }
    }
    finally {
      if (requestToken === sourceRequestToken) sourceLoading.value = false
    }
  }

  function changeSourcePage(page) {
    if (!sourceLine.value || page < 1) return
    const calculationVersion = sourceDetail.value?.calculation_version
    if (calculationVersion === undefined) {
      showToast('请从第一页重新打开来源明细', 'error')
      return
    }
    return openLineSources(sourceLine.value, page, calculationVersion)
  }

  function changeDetailPage(page) {
    const next = Number(page)
    if (!Number.isInteger(next)) return
    detailPage.value = Math.min(Math.max(next, 1), detailTotalPages.value)
    return reloadDetail()
  }

  function detailParams() {
    const params = {
      page: detailPage.value,
      limit: detailLimit.value,
      status_filter: detailStatusFilter.value,
    }
    const query = detailEmployeeQuery.value.trim()
    if (query) params.employee_query = query
    return params
  }

  async function reloadDetail() {
    if (!selectedId.value) return
    const batchId = selectedId.value
    const requestToken = ++detailRequestToken
    try {
      const result = await api.domains.wages.getPayrollBatch(batchId, detailParams())
      if (requestToken === detailRequestToken && selectedId.value === batchId) detail.value = result
    } catch (error) {
      if (requestToken === detailRequestToken) showToast(error.message || '工资明细加载失败', 'error')
    }
  }

  function resetDetailPage() {
    detailPage.value = 1
    return reloadDetail()
  }

  function runPrimaryAction(batch) {
    const action = primaryAction(batch)
    if (action.disabled) {
      showToast('当前批次仍有阻断项，请先处理后再继续', 'error')
      return
    }
    if (action.key === 'submit') return submit(batch)
    if (action.key === 'regenerate') return regenerate(batch)
    if (action.key === 'lock') return lock(batch)
    if (action.key === 'confirm') return confirmBatch(batch)
    if (action.key === 'exceptions' && typeof navigate === 'function') return navigate('wages', { wage_tab: 'exceptions' })
    if (action.key === 'settlement' && typeof navigate === 'function') return navigate('wages', { wage_tab: 'settlement' })
    return openBatch(batch)
  }

  function exportBatch(batch) { window.open(`/api/payroll/batches/${batch.id}/export`, '_blank', 'noopener') }

  onMounted(load)

  return {
    now,
    month,
    status,
    batches,
    loading,
    working,
    selectedId,
    detail,
    sourceDetail,
    sourceLoading,
    sourceLine,
    periodControl,
    controlLoading,
    canPrepare,
    canApprove,
    canExport,
    statusOptions,
    pendingExceptions,
    confirmedCount,
    monthTotal,
    filteredDetailLines,
    pagedDetailLines,
    detailPage,
    detailLimit,
    detailEmployeeQuery,
    detailStatusFilter,
    detailTotalPages,
    detailTotal,
    money,
    statusLabel,
    periodStatusLabel,
    editable,
    negativePayableCount,
    hasFormalSettlement,
    canSubmit,
    canLock,
    canConfirm,
    canRevise,
    primaryAction,
    idempotency,
    load,
    loadControl,
    createBatch,
    act,
    regenerate,
    submit,
    lock,
    confirmBatch,
    revise,
    openBatch,
    openLineSources,
    changeSourcePage,
    changeDetailPage,
    resetDetailPage,
    runPrimaryAction,
    exportBatch
  }
}
