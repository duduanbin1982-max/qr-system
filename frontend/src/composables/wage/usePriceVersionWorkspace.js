import { computed, onMounted, ref } from 'vue'
import {
  priceReferenceKey,
  useRoutePriceVersions,
} from '@/composables/useRoutePriceVersions.js'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'
import { formatUnitPrice as unitPrice } from '@/composables/wage/payrollFormat.js'

export function usePriceVersionWorkspace(props) {
  const {
    references,
    versions,
    loading,
    load,
    selectReference,
  } = useRoutePriceVersions()

  const query = ref('')

  const viewMode = ref('published')

  const editorOpen = ref(false)

  const selectedRow = ref(null)

  const approving = ref(false)

  const intentHandled = ref(false)

  const manualReviews = ref([])

  const manualLoading = ref(false)

  const canPrepare = computed(() => can('wages:prepare'))

  const canApprove = computed(() => can('wages:approve'))

  const viewOptions = [
    { value: 'published', label: '当前已发布' },
    { value: 'pending-route', label: '待发布路线' },
    { value: 'voided', label: '已作废记录' },
  ]

  const versionsByReference = computed(() => {
    const grouped = new Map()
    for (const price of versions.value) {
      const key = priceReferenceKey(price)
      if (!grouped.has(key)) grouped.set(key, [])
      grouped.get(key).push(price)
    }
    for (const prices of grouped.values()) {
      prices.sort((a, b) => `${b.valid_from || ''}:${b.id}`.localeCompare(`${a.valid_from || ''}:${a.id}`))
    }
    return grouped
  })

  const referenceRows = computed(() => references.value.map(reference => {
    const key = priceReferenceKey(reference)
    const prices = versionsByReference.value.get(key) || []
    return {
      ...reference,
      key,
      current: prices.find(price => price.status === 'approved') || null,
      draft: prices.find(price => price.status === 'draft') || null,
    }
  }))

  const publishedRows = computed(() => referenceRows.value.filter(
    row => row.route_version_status === 'published'
  ))

  const pendingRows = computed(() => referenceRows.value.filter(
    row => row.route_version_status === 'pending_approval'
  ))

  const voidedPrices = computed(() => versions.value.filter(price => price.status === 'voided'))

  const draftCount = computed(() => referenceRows.value.filter(row => row.draft).length)

  function matchesSearch(item) {
    if (!query.value) return true
    const text = [
      item.route_name,
      item.process_name,
      item.route_version_id,
      item.process_version_id,
    ].filter(Boolean).join(' ').toLocaleLowerCase('zh-CN')
    return text.includes(query.value.toLocaleLowerCase('zh-CN'))
  }

  const displayedRows = computed(() => (
    viewMode.value === 'pending-route' ? pendingRows.value : publishedRows.value
  ).filter(matchesSearch))

  const groupedRows = computed(() => {
    const groups = new Map()
    for (const row of displayedRows.value) {
      if (!groups.has(row.route_version_id)) {
        groups.set(row.route_version_id, {
          route_version_id: row.route_version_id,
          rows: [],
        })
      }
      groups.get(row.route_version_id).rows.push(row)
    }
    return [...groups.values()]
  })

  const filteredVoidedPrices = computed(() => voidedPrices.value.filter(matchesSearch))

  function routeLabel(row) {
    const state = row.route_version_status === 'published' ? '当前' : '待发布'
    return `${row.route_name} · ${state} V${row.route_version}`
  }

  function approvalMode(row) {
    return row.pricing_mode === 'pending_group_release' ? '成组发布批准' : '独立审批'
  }

  function formatDateTime(value) {
    return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
  }

  function openEditor(row) {
    selectReference(row)
    selectedRow.value = row
    editorOpen.value = true
  }

  function closeEditor() {
    editorOpen.value = false
    selectedRow.value = null
  }

  async function refresh() {
    try {
      await load()
      await refreshManualReviews()
      restoreExactIntent()
    } catch (error) {
      showToast(error.message || '工价版本加载失败', 'error')
    }
  }

  async function refreshManualReviews() {
    if (!canPrepare.value && !canApprove.value) {
      manualReviews.value = []
      return
    }
    manualLoading.value = true
    try {
      const result = await api.domains.wages.listHistoricalPriceManualReviews()
      manualReviews.value = result.items || []
    } catch (error) {
      // Older databases may not have V083 yet; keep the normal price screen usable.
      if (error.status !== 404) showToast(error.message || '历史人工确认清单加载失败', 'error')
      manualReviews.value = []
    } finally {
      manualLoading.value = false
    }
  }

  function restoreExactIntent() {
    if (intentHandled.value || !props.routeVersionId || !props.processVersionId) return
    const row = referenceRows.value.find(item => (
      Number(item.route_version_id) === Number(props.routeVersionId)
      && Number(item.process_version_id) === Number(props.processVersionId)
    ))
    if (!row) return
    viewMode.value = row.route_version_status === 'pending_approval'
      ? 'pending-route'
      : 'published'
    intentHandled.value = true
    if (props.createIntent) openEditor(row)
  }

  async function handleEditorResult() {
    closeEditor()
    await refresh()
  }

  async function approveDraft(price) {
    if (approving.value) return
    approving.value = true
    try {
      await api.domains.wages.approveRoutePriceVersion(price.id, price.row_version)
      showToast('工价版本已批准')
      await refresh()
    } catch (error) {
      showToast(error.message || '批准工价失败', 'error')
    } finally {
      approving.value = false
    }
  }

  onMounted(refresh)

  return {
    references,
    versions,
    loading,
    load,
    selectReference,
    query,
    viewMode,
    editorOpen,
    selectedRow,
    approving,
    intentHandled,
    manualReviews,
    manualLoading,
    canPrepare,
    canApprove,
    viewOptions,
    versionsByReference,
    referenceRows,
    publishedRows,
    pendingRows,
    voidedPrices,
    draftCount,
    matchesSearch,
    displayedRows,
    groupedRows,
    filteredVoidedPrices,
    routeLabel,
    approvalMode,
    unitPrice,
    formatDateTime,
    openEditor,
    closeEditor,
    refresh,
    refreshManualReviews,
    restoreExactIntent,
    handleEditorResult,
    approveDraft
  }
}
