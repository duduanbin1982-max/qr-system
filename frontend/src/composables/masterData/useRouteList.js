import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  routeLifecycleLabel,
  routeVersionStatusLabel,
  useRouteVersions,
} from '@/composables/useRouteVersions.js'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { navigate } from '@/lib/router.js'
import { showToast } from '@/lib/store.js'

export function useRouteList() {
  const state = useRouteVersions()

  const {
    selectedRoute, root, selectedVersion, currentVersion, openVersion, historicalVersions,
    comparisonBase, impact, priceVersions, coverageRows, loadingDetail, loadingContext,
    busy, operationError, contextError,
  } = state

  const routes = ref([])

  const processOptions = ref([])

  const loading = ref(false)

  const searchKeyword = ref('')

  const categoryFilter = ref('')

  const page = ref(1)

  const pageSize = 20

  const total = ref(0)

  const summary = ref({ total_routes: 0, category_counts: {}, process_nodes_total: 0 })

  const showCreateModal = ref(false)

  const showDetailModal = ref(false)

  const showCommandModal = ref(false)

  const showApprovalModal = ref(false)

  const showReleaseModal = ref(false)

  const releaseOperationBusy = ref(false)

  const releaseRefreshBusy = ref(false)

  const releaseBusy = computed(() => releaseOperationBusy.value || releaseRefreshBusy.value)

  const commandType = ref('')

  const commandReason = ref('')

  const editorForm = ref(emptyRoute())

  const createForm = ref(emptyRoute(true))

  const approvalDispositions = reactive({})

  const canCreateVersion = computed(() => can('route_versions:create'))

  const canSubmit = computed(() => can('route_versions:submit'))

  const canApprove = computed(() => can('route_versions:approve'))

  const canReject = computed(() => can('route_versions:reject'))

  const canRetire = computed(() => can('process_routes:retire'))

  const canReactivate = computed(() => can('process_routes:reactivate'))

  const canViewReleases = computed(() => can('master_data_releases:view'))

  const canPreparePrice = computed(() => can('wages:prepare'))

  const activeCategory = computed(() => categoryFilter.value || 'all')

  const historicalSelection = computed(() => historicalVersions.value.some(version => version.id === selectedVersion.value?.id) ? selectedVersion.value.id : '')

  const coveredNodeCount = computed(() => coverageRows.value.filter(exactApprovedPrice).length)

  const missingCoverageRows = computed(() => coverageRows.value.filter(row => row.coverage_status !== 'approved'))

  const commandTitle = computed(() => ({ revision: '创建路线修订版', reject: '驳回路线版本', retire: '申请路线退休', reactivate: '申请重新启用' }[commandType.value] || '路线操作'))

  const commandLabel = computed(() => commandType.value === 'revision' ? '修订原因' : commandType.value === 'reject' ? '驳回原因' : '申请原因')

  watch(selectedVersion, version => { if (version) editorForm.value = clone(version) }, { deep: true })

  function clone(value) { return JSON.parse(JSON.stringify(value || {})) }

  function emptyRoute(withReason = false) {
    return { name: '', category: '结构件', description: '', items: [], ...(withReason ? { revision_reason: '' } : {}) }
  }

  function priceStatus(status) { return ({ draft: '草稿', approved: '已批准', retired: '已结束' }[status] || status || '-') }

  function exactApprovedPrice(row) { return row.price_versions?.find(price => price.status === 'approved') || null }

  function money(micros) { return Number.isFinite(Number(micros)) ? `¥${(Number(micros) / 10000).toFixed(4)}` : '-' }

  function coverageStatusLabel(status, routeStatus) {
    if (routeStatus === 'draft') return '提交审批后可定价'
    return ({ approved: '已批准覆盖', draft: '工价草稿', voided: '工价已作废', missing: '缺少工价' }[status] || status)
  }

  function coverageStatusClass(status) { return status === 'approved' ? 'text-success' : status === 'voided' ? 'text-danger' : 'text-warning' }

  function openPriceVersion(row) {
    if (selectedVersion.value?.status !== 'pending_approval' || !canPreparePrice.value) return
    navigate('wages', {
      wage_tab: 'priceversions',
      route_version_id: Number(selectedVersion.value.id),
      process_version_id: Number(row.process_version_id),
      create_price: true,
    })
  }

  async function submitAndOpenPrice(row) {
    if (selectedVersion.value?.status !== 'draft' || !canSubmit.value || !canPreparePrice.value) return
    try {
      await state.transition('submit')
      showToast('路线已提交审批，请填写精确工价')
      openPriceVersion(row)
    } catch (error) {
      showToast(error.message || '提交审批失败，暂不能填写工价', 'error')
    }
  }

  async function load() {
    loading.value = true
    try {
      const payload = await api.domains.processRoutes.listProcessRoutes({
        category: categoryFilter.value,
        search: searchKeyword.value.trim(),
        limit: pageSize,
        offset: (page.value - 1) * pageSize,
      })
      routes.value = payload.routes || []
      total.value = payload.total ?? routes.value.length
      summary.value = payload.summary || summary.value
    } catch (error) { showToast(error.message || '路线加载失败', 'error') }
    finally { loading.value = false }
  }

  async function loadProcesses() {
    try {
      const payload = await api.domains.processes.listProcesses({ selectable: true, limit: 200 })
      processOptions.value = payload.processes || []
    } catch (error) { showToast(error.message || '工序版本选项加载失败', 'error') }
  }

  function switchCategory(category) { categoryFilter.value = category === 'all' ? '' : category; page.value = 1; load() }

  function searchAndLoad() { page.value = 1; load() }

  function clearSearch() { searchKeyword.value = ''; searchAndLoad() }

  function previousPage() { if (page.value > 1) { page.value -= 1; load() } }

  function nextPage() { if (page.value * pageSize < total.value) { page.value += 1; load() } }

  function openCreate() { createForm.value = emptyRoute(true); showCreateModal.value = true }

  async function saveNewRoute() {
    if (!createForm.value.name.trim() || !createForm.value.items.length || !createForm.value.revision_reason.trim()) {
      showToast('请填写路线名称、至少一个节点和制单原因', 'error'); return
    }
    try {
      await state.createRoute(createForm.value)
      showCreateModal.value = false
      showDetailModal.value = true
      await load()
      showToast('路线 V1 草稿已创建')
    } catch (error) { showToast(error.message || '路线创建失败', 'error') }
  }

  async function openDetail(route) {
    showDetailModal.value = true
    try { await state.openRoute(route) } catch (error) { showToast(error.message || '路线版本加载失败', 'error') }
  }

  function closeDetail() { showDetailModal.value = false; showApprovalModal.value = false; state.reset() }

  function closeReleaseModal() {
    if (releaseBusy.value) return
    showReleaseModal.value = false
  }

  async function chooseVersion(version) { await state.selectVersion(version) }

  async function chooseHistory(versionId) { if (versionId) await state.selectVersion(versionId) }

  async function startRevisionFromRow(route) {
    await openDetail(route)
    if (openVersion.value) { showToast('该路线已有开放修订版', 'warn'); return }
    openCommand('revision')
  }

  async function startLifecycleFromRow(route, action) { await openDetail(route); openCommand(action) }

  function openCommand(type) { commandType.value = type; commandReason.value = ''; showCommandModal.value = true }

  async function confirmCommand() {
    if (!commandReason.value.trim()) { showToast(`${commandLabel.value}不能为空`, 'error'); return }
    try {
      if (commandType.value === 'revision') await state.createRevision({ ...editorForm.value, revision_reason: commandReason.value })
      else if (commandType.value === 'reject') await state.transition('reject', commandReason.value)
      else await state.requestLifecycle(commandType.value, commandReason.value)
      showCommandModal.value = false
      await load()
      showToast('路线版本操作已完成')
    } catch (error) { showToast(error.message || '路线版本操作失败', 'error') }
  }

  async function saveDraft() {
    try { await state.updateDraft(editorForm.value); showToast('路线草稿已保存') } catch (error) { showToast(error.message || '保存失败', 'error') }
  }

  async function submitVersion() {
    try { await state.transition('submit'); await load(); showToast('路线版本已提交审批') } catch (error) { showToast(error.message || '提交失败', 'error') }
  }

  function openApproval() {
    Object.keys(approvalDispositions).forEach(key => delete approvalDispositions[key])
    coverageRows.value.forEach(row => { approvalDispositions[row.process_id] = { process_id: Number(row.process_id), disposition: '', price_version_id: null, reason: '' } })
    showApprovalModal.value = true
  }

  async function approveVersion() {
    try {
      await state.approveSelected(Object.values(approvalDispositions))
      showApprovalModal.value = false
      await load()
      showToast('路线版本已批准发布')
    } catch (error) { showToast(error.message || '发布失败', 'error') }
  }

  async function handleBatchPublished() {
    releaseRefreshBusy.value = true
    try {
      if (root.value?.id) await state.loadRoute(root.value.id)
      await load()
    } finally {
      releaseRefreshBusy.value = false
    }
  }

  onMounted(async () => { await Promise.all([loadProcesses(), load()]) })

  return {
    selectedRoute,
    root,
    selectedVersion,
    currentVersion,
    openVersion,
    historicalVersions,
    comparisonBase,
    impact,
    priceVersions,
    coverageRows,
    loadingDetail,
    loadingContext,
    busy,
    operationError,
    contextError,
    routes,
    processOptions,
    loading,
    searchKeyword,
    categoryFilter,
    page,
    pageSize,
    total,
    summary,
    showCreateModal,
    showDetailModal,
    showCommandModal,
    showApprovalModal,
    showReleaseModal,
    releaseOperationBusy,
    releaseBusy,
    commandType,
    commandReason,
    editorForm,
    createForm,
    approvalDispositions,
    canCreateVersion,
    canSubmit,
    canApprove,
    canReject,
    canRetire,
    canReactivate,
    canViewReleases,
    canPreparePrice,
    activeCategory,
    historicalSelection,
    coveredNodeCount,
    missingCoverageRows,
    commandTitle,
    commandLabel,
    clone,
    emptyRoute,
    priceStatus,
    exactApprovedPrice,
    money,
    coverageStatusLabel,
    coverageStatusClass,
    openPriceVersion,
    submitAndOpenPrice,
    load,
    loadProcesses,
    switchCategory,
    searchAndLoad,
    clearSearch,
    previousPage,
    nextPage,
    openCreate,
    saveNewRoute,
    openDetail,
    closeDetail,
    closeReleaseModal,
    chooseVersion,
    chooseHistory,
    startRevisionFromRow,
    startLifecycleFromRow,
    openCommand,
    confirmCommand,
    saveDraft,
    submitVersion,
    openApproval,
    approveVersion,
    handleBatchPublished,
    routeLifecycleLabel,
    routeVersionStatusLabel
  }
}
