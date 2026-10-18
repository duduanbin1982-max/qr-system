import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function usePayrollLedger() {
  const now = new Date()

  const month = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)

  const status = ref('')

  const batches = ref([])

  const loading = ref(false)

  const working = ref(false)

  const selectedId = ref(null)

  const detail = ref(null)

  const canPrepare = computed(() => can('wages:prepare'))

  const canApprove = computed(() => can('wages:approve'))

  const canExport = computed(() => can('wages:export'))

  const statusOptions = [
    { value:'draft', label:'草稿' }, { value:'exceptions_pending', label:'待异常处理' },
    { value:'review_pending', label:'待复核' }, { value:'locked', label:'已锁定' },
    { value:'confirmed', label:'已确认' }, { value:'voided', label:'已作废' },
  ]

  const pendingExceptions = computed(() => batches.value.reduce((sum, item) => sum + Number(item.exception_count || 0), 0))

  const confirmedCount = computed(() => batches.value.filter(item => item.status === 'confirmed').length)

  const monthTotal = computed(() => batches.value.filter(item => !item.superseded_by_batch_id && item.status !== 'voided').reduce((sum, item) => sum + Number(item.payable_wage_cents || 0), 0))

  function money(cents) { return `¥${(Number(cents || 0) / 100).toFixed(2)}` }

  function statusLabel(value) { return statusOptions.find(item => item.value === value)?.label || value }

  function editable(batch) { return ['draft', 'exceptions_pending'].includes(batch.status) && !batch.legacy_imported }

  function canSubmit(batch) { return batch.status === 'draft' && !batch.exception_count && !batch.legacy_imported }

  function idempotency(prefix) { return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}` }

  async function load() {
    loading.value = true
    try {
      const data = await api.domains.wages.listPayrollBatches({ payroll_month: month.value, status: status.value })
      batches.value = data.batches || []
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

  function submit(batch) { return act(() => api.domains.wages.submitPayrollBatch(batch.id, batch.row_version), '批次已提交复核') }

  function lock(batch) { return act(() => api.domains.wages.lockPayrollBatch(batch.id, batch.row_version), '批次已锁定') }

  function confirmBatch(batch) {
    if (!window.confirm(`确认 ${batch.payroll_month} / V${batch.version} 工资批次？`)) return
    return act(() => api.domains.wages.confirmPayrollBatch(batch.id, batch.row_version), '批次已确认')
  }

  function revise(batch) {
    const reason = window.prompt('请输入生成修订版的原因')
    if (!reason?.trim()) return
    return act(() => api.domains.wages.revisePayrollBatch(batch.id, { revision_reason:reason.trim(), idempotency_key:idempotency('payroll-revision') }), '修订版已生成')
  }

  async function openBatch(batch) {
    selectedId.value = batch.id
    try { detail.value = await api.domains.wages.getPayrollBatch(batch.id) }
    catch (error) { showToast(error.message || '批次明细加载失败', 'error') }
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
    canPrepare,
    canApprove,
    canExport,
    statusOptions,
    pendingExceptions,
    confirmedCount,
    monthTotal,
    money,
    statusLabel,
    editable,
    canSubmit,
    idempotency,
    load,
    createBatch,
    act,
    regenerate,
    submit,
    lock,
    confirmBatch,
    revise,
    openBatch,
    exportBatch
  }
}
