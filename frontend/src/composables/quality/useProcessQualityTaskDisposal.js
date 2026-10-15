import { computed, reactive, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function useProcessQualityTaskDisposal(props, emit) {
  const PAGE_SIZE = 50

  const tasks = ref([]), summary = ref({}), status = ref('pending')

  const page = ref(1), total = ref(0), selectedTaskIds = ref([])

  const showWaiver = ref(false), waiving = ref(false), waiverPreviewing = ref(false), waiverPreview = ref(null)

  const waiverForm = reactive({ taskIds: [], orderId: null, orderNo: '', scope: '', reasonCode: '', reason: '' })

  const pages = computed(() => pageCount(total.value))

  const waiverPolicy = computed(() => summary.value.waiver_policy || {})

  const canWaiveLive = computed(() => Boolean(waiverPolicy.value.can_waive_live))

  const disposableTasks = computed(() => tasks.value.filter(task => task.status === 'pending' && canWaiveTask(task)))

  const allPendingSelected = computed(() => status.value === 'pending' && disposableTasks.value.length > 0 && selectedTaskIds.value.length === disposableTasks.value.length)

  const waiverReasonOptions = computed(() => waiverForm.scope === 'live' ? (waiverPolicy.value.live_reasons || []) : waiverForm.scope === 'historical' ? (waiverPolicy.value.historical_reasons || []) : [])

  const emptyText = computed(() => ({ pending: '待处置', waived: '已豁免', audit: '永久审计' }[status.value] || ''))

  const waiverTitle = computed(() => waiverForm.orderId ? '豁免本订单必评任务' : '豁免评价任务')

  const waiverTargetLabel = computed(() => { const count = waiverPreview.value?.task_count || waiverForm.taskIds.length; const target = waiverForm.orderId ? `订单 ${waiverForm.orderNo || waiverForm.orderId} 的 ${count} 条待处理必评任务` : `已选择的 ${count} 条待评价任务`; return waiverForm.scope === 'live' ? `${target}属于生产中或待生产订单。` : waiverForm.scope === 'historical' ? `${target}将按历史任务留痕处置。` : `${target}包含不同处置范围，不能提交。` })

  function pageCount(value) { return Math.max(1, Math.ceil((Number(value) || 0) / PAGE_SIZE)) }

  async function reload({ resetPage = false } = {}) { if (resetPage) page.value = 1; const params = { keyword: props.keyword, page: page.value, per_page: PAGE_SIZE }; try { const request = status.value === 'audit' ? api.domains.processQualityEvaluations.qualityEvaluationTaskAudits(params) : api.domains.processQualityEvaluations.qualityEvaluationTasks({ ...params, scope: 'all', status: status.value }); const [summaryData, taskData] = await Promise.all([api.domains.processQualityEvaluations.qualityEvaluationTaskDisposalSummary(), request]); const lastPage = pageCount(taskData.total); if (page.value > lastPage) { page.value = lastPage; return reload() } summary.value = summaryData || {}; tasks.value = taskData.items || []; total.value = taskData.total || 0; emit('summary', summary.value); const visibleIds = new Set(tasks.value.filter(task => task.status === 'pending').map(task => task.id)); selectedTaskIds.value = selectedTaskIds.value.filter(id => visibleIds.has(id)) } catch (error) { showToast(error.message || '任务处置数据加载失败', 'error') } }

  async function changeStatus() { page.value = 1; selectedTaskIds.value = []; await reload() }

  async function changePage(delta) { page.value += delta; selectedTaskIds.value = []; await reload() }

  function toggleTask(taskId, checked) { selectedTaskIds.value = checked ? [...new Set([...selectedTaskIds.value, taskId])] : selectedTaskIds.value.filter(id => id !== taskId) }

  function toggleAll(checked) { selectedTaskIds.value = checked ? disposableTasks.value.map(task => task.id) : [] }

  function waiverScopeForTask(task) { return task.order_deleted_at || ['completed', 'cancelled'].includes(task.order_status) ? 'historical' : 'live' }

  function canWaiveTask(task) { return waiverScopeForTask(task) === 'historical' || canWaiveLive.value }

  function orderStatusLabel(value) { return { completed: '已完成', cancelled: '已取消', pending: '待生产', producing: '生产中', paused: '已暂停' }[value] || value || '-' }

  function orderStatusText(task) { return task.order_deleted_at ? '已归档' : orderStatusLabel(task.order_status) }

  function waiverReasonLabel(code) { if (!code || code === 'legacy_unclassified') return '历史记录未分类'; const options = [...(waiverPolicy.value.historical_reasons || []), ...(waiverPolicy.value.live_reasons || [])]; return options.find(option => option.code === code)?.label || code }

  function waiverPayload() { return waiverForm.orderId ? { order_id: waiverForm.orderId, required_only: true } : { task_ids: waiverForm.taskIds } }

  async function openWaiverPreview(formValues) { if (waiverPreviewing.value) return; waiverPreviewing.value = true; try { const preview = await api.domains.processQualityEvaluations.previewQualityEvaluationTaskWaiver(formValues.orderId ? { order_id: formValues.orderId, required_only: true } : { task_ids: formValues.taskIds }); waiverPreview.value = preview; Object.assign(waiverForm, { ...formValues, scope: preview.waiver_scope, reasonCode: '', reason: '' }); showWaiver.value = true } catch (error) { showToast(error.message || '豁免影响预览失败', 'error') } finally { waiverPreviewing.value = false } }

  async function openWaiver(taskIds) { await openWaiverPreview({ taskIds: [...new Set(taskIds)], orderId: null, orderNo: '' }) }

  async function openOrderWaiver(task) { await openWaiverPreview({ taskIds: [], orderId: task.order_id, orderNo: task.order_no }) }

  async function saveWaiver() { if (!waiverPreview.value?.can_submit) { showToast('当前选择不能提交，请根据风险提示调整任务范围', 'error'); return } if (!waiverForm.reasonCode) { showToast('请选择豁免原因类型', 'error'); return } const minimumLength = waiverForm.scope === 'live' ? 10 : 2; if (waiverForm.reason.trim().length < minimumLength) { showToast(`请填写至少${minimumLength}个字符的豁免说明`, 'error'); return } waiving.value = true; try { const result = await api.domains.processQualityEvaluations.waiveQualityEvaluationTasks({ ...waiverPayload(), reason_code: waiverForm.reasonCode, reason: waiverForm.reason.trim() }); showWaiver.value = false; waiverPreview.value = null; selectedTaskIds.value = []; showToast(`已豁免 ${result.count || 0} 条评价任务`); await reload(); emit('waived') } catch (error) { showToast(error.message || '豁免失败', 'error') } finally { waiving.value = false } }

  function taskAgeText(task) { const hours = Math.max(0, Number(task.age_hours) || 0); return task.age_level === 'critical' ? `超时 ${Math.floor(hours)} 小时` : task.age_level === 'warning' ? `已 ${Math.floor(hours)} 小时` : '24小时内' }

  function taskAgeClass(task) { return { critical: 'text-danger', warning: 'text-warning' }[task.age_level] || '' }

  return {
    PAGE_SIZE,
    tasks,
    summary,
    status,
    page,
    total,
    selectedTaskIds,
    showWaiver,
    waiving,
    waiverPreviewing,
    waiverPreview,
    waiverForm,
    pages,
    waiverPolicy,
    canWaiveLive,
    disposableTasks,
    allPendingSelected,
    waiverReasonOptions,
    emptyText,
    waiverTitle,
    waiverTargetLabel,
    pageCount,
    reload,
    changeStatus,
    changePage,
    toggleTask,
    toggleAll,
    waiverScopeForTask,
    canWaiveTask,
    orderStatusLabel,
    orderStatusText,
    waiverReasonLabel,
    waiverPayload,
    openWaiverPreview,
    openWaiver,
    openOrderWaiver,
    saveWaiver,
    taskAgeText,
    taskAgeClass
  }
}
