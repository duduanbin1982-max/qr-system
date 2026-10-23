import { computed, onMounted, reactive, ref, watch } from 'vue'
import { releaseStatusLabel, useMasterDataReleases } from '@/composables/useMasterDataReleases.js'
import { routeVersionStatusLabel } from '@/composables/useRouteVersions.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function useReleaseBatchPanel(props, emit) {
  const state = useMasterDataReleases()

  const { batches, selectedBatch, loading, busy, operationError } = state

  watch(busy, value => emit('busy-change', value), { immediate: true })

  const statusFilter = ref('')

  const showCreate = ref(false)

  const dispositions = reactive({})

  const dispositionError = ref('')

  const createForm = reactive({ release_no: '', revision_reason: '', process_version_ids: [], route_version_ids: [], price_version_ids: [] })

  const canCreate = computed(() => can('master_data_releases:create'))

  const canSubmit = computed(() => can('master_data_releases:submit'))

  const canApprove = computed(() => can('master_data_releases:approve'))

  const canReject = computed(() => can('master_data_releases:reject'))

  const uniqueNodes = computed(() => {
    const byProcess = new Map()
    ;(selectedBatch.value?.route_versions || []).forEach(route => {
      ;(route.items || []).forEach(node => { if (!byProcess.has(Number(node.process_id))) byProcess.set(Number(node.process_id), node) })
    })
    return [...byProcess.values()]
  })

  const approvalReady = computed(() => {
    try {
      state.validatePriceDispositions(Object.values(dispositions))
      return true
    } catch (_) {
      return false
    }
  })

  const routeNodeBindings = computed(() => new Set(
    (selectedBatch.value?.route_versions || []).flatMap(route => (
      route.items || []
    ).map(node => `${Number(route.id)}:${Number(node.process_version_id)}`))
  ))

  const invalidPrices = computed(() => (selectedBatch.value?.price_versions || []).filter(
    price => price.status === 'voided' || !routeNodeBindings.value.has(
      `${Number(price.route_version_id)}:${Number(price.process_version_id)}`
    )
  ))

  const invalidPriceIds = computed(() => new Set(invalidPrices.value.map(price => Number(price.id))))

  watch(uniqueNodes, nodes => {
    Object.keys(dispositions).forEach(key => delete dispositions[key])
    nodes.forEach(node => {
      dispositions[node.process_id] = { process_id: Number(node.process_id), disposition: '', price_version_id: null, reason: '' }
    })
  }, { immediate: true })

  function versionStatus(status) { return routeVersionStatusLabel(status) }

  function priceStatus(status) { return ({ draft: '草稿', approved: '已批准', retired: '已结束' }[status] || status || '-') }

  function money(micros) { return Number.isFinite(Number(micros)) ? `¥${(Number(micros) / 1000000).toFixed(4)}` : '-' }

  function exactPrices(node) {
    return (selectedBatch.value?.price_versions || []).filter(price => (
      Number(price.process_version_id) === Number(node.process_version_id)
      && ['draft', 'approved'].includes(price.status)
    ))
  }

  async function reload() {
    try {
      await state.loadBatches(statusFilter.value)
      if (selectedBatch.value?.id) await state.loadBatch(selectedBatch.value.id)
    } catch (error) {
      showToast(error.message || '发布批次加载失败', 'error')
    }
  }

  async function selectBatch(batchId) {
    try { await state.loadBatch(batchId) } catch (error) { showToast(error.message || '批次详情加载失败', 'error') }
  }

  function openCreate() {
    const route = props.defaultRouteVersion
    createForm.release_no = `MDR-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-01`
    createForm.revision_reason = route ? `发布路线 ${route.name} V${route.version}` : ''
    createForm.route_version_ids = route?.id ? [Number(route.id)] : []
    createForm.process_version_ids = [...new Set((route?.items || []).filter(node => node.process_version_status !== 'published').map(node => Number(node.process_version_id)))]
    createForm.price_version_ids = props.defaultPriceVersions.filter(price => (
      price.status === 'draft'
      && Number(price.route_version_id) === Number(route?.id)
      && (route?.items || []).some(node => Number(node.process_version_id) === Number(price.process_version_id))
    )).map(price => Number(price.id))
    showCreate.value = true
  }

  async function createSelected() {
    try {
      await state.createBatch(createForm)
      showCreate.value = false
      showToast('成组发布批次已创建')
    } catch (error) { showToast(error.message || '创建发布批次失败', 'error') }
  }

  async function submitSelected() {
    try { await state.submitBatch(); showToast('发布批次已提交审批') } catch (error) { showToast(error.message || '提交失败', 'error') }
  }

  async function approveSelected() {
    dispositionError.value = ''
    try {
      await state.approveBatch(Object.values(dispositions))
      showToast('主数据批次已原子发布')
      emit('published', selectedBatch.value)
    } catch (error) {
      dispositionError.value = error.message || '批准失败'
      showToast(dispositionError.value, 'error')
    }
  }

  async function rejectSelected() {
    const reason = globalThis.prompt?.('请输入驳回原因')
    if (!reason) return
    try { await state.rejectBatch(reason); showToast('发布批次已驳回') } catch (error) { showToast(error.message || '驳回失败', 'error') }
  }

  async function removeInvalidPrice(price) {
    const reason = globalThis.prompt?.('请输入移除原因')
    if (!reason) return
    try {
      await state.removeMember('price_version', price.id, reason)
      showToast('失效工价成员已移除')
    } catch (error) { showToast(error.message || '移除失败', 'error') }
  }

  async function replaceInvalidPrice(price) {
    const replacementId = Number(globalThis.prompt?.('请输入替换工价版本 ID'))
    if (!replacementId) return
    const reason = globalThis.prompt?.('请输入替换原因')
    if (!reason) return
    try {
      await state.replaceMember('price_version', price.id, replacementId, reason)
      showToast('失效工价成员已替换')
    } catch (error) { showToast(error.message || '替换失败', 'error') }
  }

  onMounted(reload)

  return {
    batches,
    selectedBatch,
    loading,
    busy,
    operationError,
    statusFilter,
    showCreate,
    dispositions,
    dispositionError,
    createForm,
    canCreate,
    canSubmit,
    canApprove,
    canReject,
    uniqueNodes,
    approvalReady,
    routeNodeBindings,
    invalidPrices,
    invalidPriceIds,
    versionStatus,
    priceStatus,
    money,
    exactPrices,
    reload,
    selectBatch,
    openCreate,
    createSelected,
    submitSelected,
    approveSelected,
    rejectSelected,
    removeInvalidPrice,
    replaceInvalidPrice,
    releaseStatusLabel
  }
}
