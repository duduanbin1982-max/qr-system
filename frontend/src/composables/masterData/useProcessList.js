import { computed, onMounted, ref, watch } from 'vue'
import {
  processLifecycleLabel,
  processVersionErrorMessage,
  processVersionStatusLabel,
  useProcessVersions,
} from '@/composables/useProcessVersions.js'
import { can } from '@/lib/auth.js'
import { api } from '@/lib/api.js'
import { router } from '@/lib/router.js'
import { showToast } from '@/lib/store.js'

const EMPTY_CREATE_FORM = () => ({
  name: '',
  category: '结构件',
  description: '',
  seq_order: 0,
  revision_reason: '',
})

export function useProcessList() {
  const processes = ref([])
  const loading = ref(true)
  const filterCategory = ref('')
  const searchKeyword = ref('')
  const page = ref(1)
  const pageSize = ref(20)
  const total = ref(0)
  const structCount = ref(0)
  const machCount = ref(0)
  const showCreateModal = ref(false)
  const showDetailModal = ref(false)
  const showRevisionModal = ref(false)
  const showRejectModal = ref(false)
  const showLifecycleModal = ref(false)
  const createForm = ref(EMPTY_CREATE_FORM())
  const detailForm = ref({ name: '', category: '结构件', description: '', seq_order: 0 })
  const revisionReason = ref('')
  const rejectReason = ref('')
  const lifecycleReason = ref('')
  const lifecycleAction = ref('retire')
  const processDetails = ref({})

  const versionState = useProcessVersions()
  const {
    selectedProcess,
    root,
    versions,
    selectedVersion,
    currentVersion,
    openVersion,
    historicalVersions,
    comparisonBase,
    impact,
    loadingDetail,
    loadingImpact,
    impactError,
    busy,
    operationError,
  } = versionState

  const categories = ['结构件', '机加工']
  const activeCat = computed(() => filterCategory.value || 'all')
  const processTotal = computed(() => structCount.value + machCount.value)
  const pageTitle = computed(() => {
    if (filterCategory.value === '结构件') return '结构件工序'
    if (filterCategory.value === '机加工') return '机加工工序'
    return '全部工序'
  })
  const versionEditable = computed(() => selectedVersion.value?.status === 'draft')
  const revisionBaseVersion = computed(() => currentVersion.value || selectedVersion.value)
  const detailDirty = computed(() => {
    const selected = selectedVersion.value
    if (!selected || selected.status !== 'draft') return false
    return (
      String(detailForm.value.name || '').trim() !== String(selected.name || '').trim()
      || detailForm.value.category !== selected.category
      || String(detailForm.value.description || '') !== String(selected.description || '')
      || Number(detailForm.value.seq_order || 0) !== Number(selected.seq_order || 0)
    )
  })
  const historicalSelectedId = computed(() => {
    const selectedId = selectedVersion.value?.id
    return historicalVersions.value.some((item) => item.id === selectedId) ? selectedId : ''
  })

  const canCreateVersion = computed(() => can('process_versions:create'))
  const canSubmit = computed(() => can('process_versions:submit'))
  const canApprove = computed(() => can('process_versions:approve'))
  const canReject = computed(() => can('process_versions:reject'))
  const canRetire = computed(() => can('processes:retire'))
  const canReactivate = computed(() => can('processes:reactivate'))

  function categoryFromPage(routePage) {
    if (routePage === 'structure-processes') return '结构件'
    if (routePage === 'machining-processes') return '机加工'
    return ''
  }

  function processMeta(process) {
    return processDetails.value[process.id] || {}
  }

  function lifecycleStatus(process) {
    return processMeta(process).lifecycle_status || process.lifecycle_status || ''
  }

  function revisionStatus(process) {
    const meta = processMeta(process)
    return meta.open_version?.status || process.open_version_status || process.version_status || ''
  }

  function versionNumber(process) {
    const meta = processMeta(process)
    const current = meta.current_version
    const number = current?.version ?? process.process_version
    return number == null ? '-' : `V${number}`
  }

  function referenceDisplay(process) {
    const value = processMeta(process).total_references ?? process.total_references
    return value == null ? '查看' : value
  }

  function rememberDetail() {
    if (!root.value?.id) return
    processDetails.value = {
      ...processDetails.value,
      [root.value.id]: {
        process_code: root.value.process_code,
        lifecycle_status: root.value.lifecycle_status,
        current_version: currentVersion.value,
        open_version: openVersion.value,
        total_references: impact.value?.total_references,
      },
    }
  }

  async function load(options = {}) {
    const silent = options.silent === true
    loading.value = true
    try {
      const params = {
        sort_by: 'seq_order',
        sort_dir: 'asc',
        limit: pageSize.value,
        offset: (page.value - 1) * pageSize.value,
      }
      if (filterCategory.value) params.category = filterCategory.value
      if (searchKeyword.value.trim()) params.search = searchKeyword.value.trim()
      const payload = await api.domains.processes.listProcesses(params)
      const data = payload.processes || []
      processes.value = data
      total.value = payload.total != null ? payload.total : data.length
      if (payload.category_counts) {
        structCount.value = payload.category_counts['结构件'] || 0
        machCount.value = payload.category_counts['机加工'] || 0
      }
    } catch (error) {
      if (silent) throw error
      showToast(error.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  function switchCat(category) {
    const nextCategory = category === 'all' ? '' : category
    if (filterCategory.value === nextCategory) return
    filterCategory.value = nextCategory
    page.value = 1
    load()
  }

  function searchAndLoad() {
    page.value = 1
    load()
  }

  function clearSearch() {
    searchKeyword.value = ''
    searchAndLoad()
  }

  function prevPage() {
    if (page.value > 1) {
      page.value -= 1
      load()
    }
  }

  function nextPage() {
    if (page.value * pageSize.value < total.value) {
      page.value += 1
      load()
    }
  }

  function openAdd() {
    createForm.value = EMPTY_CREATE_FORM()
    showCreateModal.value = true
  }

  function closeCreateModal() {
    if (!busy.value) showCreateModal.value = false
  }

  function validateContent(form, requireReason = false) {
    if (!String(form.name || '').trim()) {
      showToast('请输入工序名称', 'error')
      return false
    }
    if (requireReason && String(form.revision_reason || '').trim().length < 2) {
      showToast('请填写至少 2 个字符的制单原因', 'error')
      return false
    }
    return true
  }

  async function saveNewProcess() {
    if (!validateContent(createForm.value, true)) return
    try {
      await versionState.createProcess(createForm.value)
      rememberDetail()
      showCreateModal.value = false
      showDetailModal.value = true
      showToast('V1 草稿已创建')
      await load()
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  async function openDetail(process) {
    showDetailModal.value = true
    try {
      await versionState.openProcess(process)
      rememberDetail()
      return true
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
      return false
    }
  }

  function closeDetail() {
    if (busy.value) return
    showDetailModal.value = false
    showRevisionModal.value = false
    showRejectModal.value = false
    showLifecycleModal.value = false
    versionState.reset()
  }

  async function chooseVersion(version) {
    try {
      await versionState.selectVersion(version)
      rememberDetail()
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  function chooseHistoricalVersion(event) {
    if (event.target.value) chooseVersion(Number(event.target.value))
  }

  function fillDetailForm(version) {
    if (!version) return
    detailForm.value = {
      name: version.name || '',
      category: version.category || '结构件',
      description: version.description || '',
      seq_order: Number(version.seq_order || 0),
    }
  }

  async function afterVersionOperation(message) {
    rememberDetail()
    showToast(message)
    await load()
  }

  async function saveDraft() {
    if (!validateContent(detailForm.value)) return
    try {
      await versionState.updateDraft(detailForm.value)
      await afterVersionOperation('草稿已保存')
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  async function submitVersion() {
    try {
      await versionState.transition('submit')
      await afterVersionOperation('版本已提交审批')
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  async function approveVersion() {
    try {
      await versionState.transition('approve')
      await afterVersionOperation('版本已批准并发布')
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  function openRejectDialog() {
    rejectReason.value = ''
    showRejectModal.value = true
  }

  async function rejectVersion() {
    if (rejectReason.value.trim().length < 2) {
      showToast('请填写至少 2 个字符的驳回原因', 'error')
      return
    }
    try {
      await versionState.transition('reject', rejectReason.value)
      showRejectModal.value = false
      await afterVersionOperation('版本已驳回')
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  function openRevisionDialog() {
    if (openVersion.value) {
      chooseVersion(openVersion.value)
      showToast('该工序已有开放修订版，请继续处理现有版本', 'error')
      return
    }
    revisionReason.value = ''
    showRevisionModal.value = true
  }

  async function startRevisionFromRow(process) {
    if (busy.value) return
    if (await openDetail(process)) openRevisionDialog()
  }

  async function createRevisionVersion() {
    if (revisionReason.value.trim().length < 2) {
      showToast('请填写至少 2 个字符的修订原因', 'error')
      return
    }
    const base = revisionBaseVersion.value
    if (!base) {
      showToast('未找到可修订的当前版本', 'error')
      return
    }
    try {
      await versionState.createRevision({
        name: base.name,
        category: base.category,
        description: base.description,
        seq_order: base.seq_order,
        revision_reason: revisionReason.value,
      })
      showRevisionModal.value = false
      await afterVersionOperation('修订版草稿已创建')
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  function openLifecycleDialog(action) {
    lifecycleAction.value = action
    lifecycleReason.value = ''
    showLifecycleModal.value = true
  }

  async function openLifecycleFromRow(process, action) {
    if (busy.value) return
    if (await openDetail(process)) openLifecycleDialog(action)
  }

  async function requestLifecycleChange() {
    if (lifecycleReason.value.trim().length < 2) {
      showToast('请填写至少 2 个字符的申请原因', 'error')
      return
    }
    try {
      await versionState.requestLifecycle(lifecycleAction.value, lifecycleReason.value)
      showLifecycleModal.value = false
      await afterVersionOperation(lifecycleAction.value === 'retire' ? '退休申请已提交' : '重新启用申请已提交')
    } catch (error) {
      showToast(processVersionErrorMessage(error), 'error')
    }
  }

  watch(selectedVersion, fillDetailForm)

  let loadedOnce = false
  onMounted(async () => {
    filterCategory.value = categoryFromPage(router.page)
    loadedOnce = true
    for (let retry = 0; retry < 3; retry += 1) {
      try {
        await load({ silent: true })
        break
      } catch (error) {
        if (retry === 2) {
          showToast('加载工序数据失败，请刷新重试', 'error')
          break
        }
        await new Promise((resolve) => setTimeout(resolve, 1000 * (retry + 1)))
      }
    }
  })

  watch(() => router.page, (routePage) => {
    const category = categoryFromPage(routePage)
    if (!loadedOnce) {
      loadedOnce = true
      return
    }
    if (filterCategory.value !== category) {
      filterCategory.value = category
      page.value = 1
      load()
    }
  })

  return {
    processes,
    loading,
    searchKeyword,
    page,
    pageSize,
    total,
    structCount,
    machCount,
    processTotal,
    pageTitle,
    activeCat,
    categories,
    showCreateModal,
    showDetailModal,
    showRevisionModal,
    showRejectModal,
    showLifecycleModal,
    createForm,
    detailForm,
    revisionReason,
    rejectReason,
    lifecycleReason,
    lifecycleAction,
    selectedProcess,
    root,
    versions,
    selectedVersion,
    currentVersion,
    openVersion,
    historicalVersions,
    comparisonBase,
    impact,
    loadingDetail,
    loadingImpact,
    impactError,
    busy,
    operationError,
    versionEditable,
    revisionBaseVersion,
    detailDirty,
    historicalSelectedId,
    canCreateVersion,
    canSubmit,
    canApprove,
    canReject,
    canRetire,
    canReactivate,
    processMeta,
    lifecycleStatus,
    revisionStatus,
    versionNumber,
    referenceDisplay,
    processVersionStatusLabel,
    processLifecycleLabel,
    switchCat,
    searchAndLoad,
    clearSearch,
    prevPage,
    nextPage,
    openAdd,
    closeCreateModal,
    saveNewProcess,
    openDetail,
    closeDetail,
    chooseVersion,
    chooseHistoricalVersion,
    saveDraft,
    submitVersion,
    approveVersion,
    openRejectDialog,
    rejectVersion,
    openRevisionDialog,
    startRevisionFromRow,
    createRevisionVersion,
    openLifecycleDialog,
    openLifecycleFromRow,
    requestLifecycleChange,
  }
}
