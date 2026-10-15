import { computed, ref, toRef } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { routeSeqLabel, useRouteWorkTimeStandards } from '@/composables/useRouteWorkTimeStandards.js'

export function useWorkTimeStandardsPanel(props, emit) {
  function today() {
    return new Date().toISOString().slice(0, 10)
  }

  const processRoutesRef = toRef(props, 'processRoutes')

  const {
    standardRows,
    enabledRowsCount,
    normalizeRouteProcesses,
    buildStandardRows,
    setAllStandardRows,
    validateStandardRows,
    buildSavePayload,
  } = useRouteWorkTimeStandards(processRoutesRef)

  const standards = ref([])

  const allStandardGroups = ref([])

  const collapsedGroupKeys = ref(new Set())

  const isLoading = ref(false)

  const isSaving = ref(false)

  const showStandardModal = ref(false)

  const standardFilters = ref({ scope: 'all', route_id: '', process_id: '' })

  const includeHistory = ref(false)

  const standardForm = ref({ route_id: '', effective_from: today() })

  const routeVersionOptions = ref([])

  const batchDefaults = ref({ standard_minutes_per_unit: 5, setup_minutes: 0, difficulty_factor: 1 })

  const filterRouteProcesses = computed(() =>
    standardFilters.value.route_id
      ? normalizeRouteProcesses(standardFilters.value.route_id)
      : props.processes.map(p => ({ id: p.id, name: p.name, seqLabel: '' }))
  )

  const standardGroups = computed(() => allStandardGroups.value
    .map(group => {
      const allItems = group.items || []
      return {
        ...group,
        all_items: allItems,
        items: allItems.filter(matchesStandardScope),
      }
    })
    .filter(group => group.items.length)
  )

  const standardOverview = computed(() => {
    const items = allStandardGroups.value.flatMap(group => group.items || [])
    return {
      total: items.length,
      configured: items.filter(item => item.id).length,
      unconfigured: items.filter(item => !item.id).length,
      active: items.filter(item => item.status === 'active').length,
      inactive: items.filter(item => item.id && item.status !== 'active').length,
    }
  })

  const visibleStandardItemCount = computed(() => standardGroups.value.reduce((sum, group) => sum + group.items.length, 0))

  const hasStandardFilters = computed(() => standardFilters.value.scope !== 'all' || !!standardFilters.value.route_id || !!standardFilters.value.process_id || includeHistory.value)

  const standardScopeOptions = computed(() => [
    { key: 'all', label: '全部', count: standardOverview.value.total },
    { key: 'unconfigured', label: '未设置', count: standardOverview.value.unconfigured },
    { key: 'configured', label: '已设置', count: standardOverview.value.configured },
    { key: 'active', label: '启用', count: standardOverview.value.active },
    { key: 'inactive', label: '停用', count: standardOverview.value.inactive },
  ])

  function groupAllItems(group) {
    return group?.all_items || group?.items || []
  }

  function activeStandardCount(group) {
    return groupAllItems(group).filter(item => item.status === 'active').length
  }

  function configuredStandardCount(group) {
    return groupAllItems(group).filter(item => item.id).length
  }

  function unconfiguredStandardCount(group) {
    return totalStandardCount(group) - configuredStandardCount(group)
  }

  function totalStandardCount(group) {
    return groupAllItems(group).length
  }

  function matchesStandardScope(row) {
    const scope = standardFilters.value.scope
    if (scope === 'unconfigured') return !row.id
    if (scope === 'configured') return !!row.id
    if (scope === 'active') return row.status === 'active'
    if (scope === 'inactive') return !!row.id && row.status !== 'active'
    return true
  }

  function setStandardScope(scope) {
    standardFilters.value.scope = scope
  }

  function clearStandardFilters() {
    standardFilters.value = { scope: 'all', route_id: '', process_id: '' }
    includeHistory.value = false
    load()
  }

  function standardGroupKey(group) {
    return String(group.route_version_id || `${group.route_id || 'no-route'}:${group.route_version || ''}`)
  }

  function isEditableGroup(group) {
    return Boolean(group?.is_current_version && group?.route_version_status === 'published')
  }

  function isGroupCollapsed(group) {
    return collapsedGroupKeys.value.has(standardGroupKey(group))
  }

  function toggleGroupCollapse(group) {
    const next = new Set(collapsedGroupKeys.value)
    const key = standardGroupKey(group)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    collapsedGroupKeys.value = next
  }

  function collapseAllGroups() {
    collapsedGroupKeys.value = new Set(standardGroups.value.map(group => standardGroupKey(group)))
  }

  function expandAllGroups() {
    collapsedGroupKeys.value = new Set()
  }

  function standardStatusLabel(row) {
    if (!row.id) return '未设置'
    return row.status === 'active' ? '启用' : '停用'
  }

  function standardStatusClass(row) {
    if (!row.id) return 'badge-warning'
    return row.status === 'active' ? 'badge-success' : 'badge-default'
  }

  async function load() {
    isLoading.value = true
    try {
      const params = {
        route_id: standardFilters.value.route_id,
        process_id: standardFilters.value.process_id,
        keyword: props.keyword,
        include_history: includeHistory.value,
        limit: 200,
      }
      const result = await api.domains.workTime.listWorkTimeStandardRoutes(params)
      const nextGroups = result.route_groups || []
      standards.value = result.items || []
      allStandardGroups.value = nextGroups
      collapsedGroupKeys.value = new Set(nextGroups.map(group => standardGroupKey(group)))
    } finally {
      isLoading.value = false
    }
  }

  function onFilterRouteChange() {
    const allowed = normalizeRouteProcesses(standardFilters.value.route_id).map(item => String(item.id))
    if (standardFilters.value.process_id && allowed.length && !allowed.includes(String(standardFilters.value.process_id))) {
      standardFilters.value.process_id = ''
    }
    load()
  }

  async function onStandardRouteChange() {
    const result = await api.domains.workTime.listWorkTimeStandardRoutes({ route_id: standardForm.value.route_id, limit: 200 })
    routeVersionOptions.value = result.route_groups || []
    const current = routeVersionOptions.value.find(item => item.is_current_version) || routeVersionOptions.value[0]
    standardForm.value.route_version_id = current?.route_version_id || ''
    await onStandardRouteVersionChange()
  }

  async function onStandardRouteVersionChange() {
    const group = routeVersionOptions.value.find(item => String(item.route_version_id) === String(standardForm.value.route_version_id))
    await buildStandardRows(standardForm.value.route_id, group?.items || [])
  }

  async function openStandardGroup(group) {
    if (group && !isEditableGroup(group)) {
      showToast('历史路线版本仅供审计查看，不能直接编辑', 'error')
      return
    }
    const routeId = group?.route_id || standardFilters.value.route_id || ''
    standardForm.value = { route_id: routeId, route_version_id: group?.route_version_id || '', effective_from: today() }
    routeVersionOptions.value = []
    standardRows.value = []
    showStandardModal.value = true
    if (routeId) {
      await onStandardRouteChange()
      if (group?.route_version_id) {
        standardForm.value.route_version_id = group.route_version_id
        await onStandardRouteVersionChange()
      }
    }
  }

  function isEmptyValue(value) {
    return value === '' || value === null || value === undefined
  }

  function copyStandardValues(target, source) {
    target.enabled = source.enabled
    target.standard_minutes_per_unit = source.standard_minutes_per_unit
    target.setup_minutes = source.setup_minutes
    target.difficulty_factor = source.difficulty_factor
    target.remark = source.remark || target.remark || ''
  }

  function fillEmptyRowsWithDefaults() {
    standardRows.value.forEach(row => {
      if (!row.enabled) return
      if (isEmptyValue(row.standard_minutes_per_unit)) row.standard_minutes_per_unit = batchDefaults.value.standard_minutes_per_unit
      if (isEmptyValue(row.setup_minutes)) row.setup_minutes = batchDefaults.value.setup_minutes
      if (isEmptyValue(row.difficulty_factor)) row.difficulty_factor = batchDefaults.value.difficulty_factor
    })
    showToast('已填充空白工时')
  }

  function applyFirstEnabledRowToAll() {
    const source = standardRows.value.find(row => row.enabled) || standardRows.value[0]
    if (!source) return
    standardRows.value.forEach(row => {
      if (row === source) return
      copyStandardValues(row, source)
    })
    showToast('已将首行工时应用到全部工序')
  }

  function copyPreviousRow(index) {
    const previous = standardRows.value[index - 1]
    const current = standardRows.value[index]
    if (!previous || !current) return
    copyStandardValues(current, previous)
  }

  async function saveStandard() {
    try {
      const routeId = standardForm.value.route_id
      if (!routeId) {
        showToast('请选择工序路线', 'error')
        return
      }
      const validationError = validateStandardRows()
      if (validationError) {
        showToast(validationError, 'error')
        return
      }
      isSaving.value = true
      const payload = buildSavePayload(routeId, standardForm.value.effective_from || today())
      payload.route_version_id = standardForm.value.route_version_id || undefined
      if (!payload.route_version_id) {
        showToast('必须选择具体路线版本后才能保存工时', 'error')
        return
      }
      await api.domains.workTime.saveRouteWorkTimeStandards(payload)
      showToast('路线标准工时已保存')
      showStandardModal.value = false
      await load()
      emit('changed')
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    } finally {
      isSaving.value = false
    }
  }

  async function deactivateStandard(row) {
    if (!confirm('确定停用该标准工时吗？')) return
    try {
      await api.domains.workTime.deleteWorkTimeStandard(row.id)
      showToast('标准工时已停用')
      await load()
      emit('changed')
    } catch (error) {
      showToast(error.message || '停用失败', 'error')
    }
  }

  return {
    today,
    processRoutesRef,
    standardRows,
    enabledRowsCount,
    normalizeRouteProcesses,
    buildStandardRows,
    setAllStandardRows,
    validateStandardRows,
    buildSavePayload,
    standards,
    allStandardGroups,
    collapsedGroupKeys,
    isLoading,
    isSaving,
    showStandardModal,
    standardFilters,
    includeHistory,
    standardForm,
    routeVersionOptions,
    batchDefaults,
    filterRouteProcesses,
    standardGroups,
    standardOverview,
    visibleStandardItemCount,
    hasStandardFilters,
    standardScopeOptions,
    groupAllItems,
    activeStandardCount,
    configuredStandardCount,
    unconfiguredStandardCount,
    totalStandardCount,
    matchesStandardScope,
    setStandardScope,
    clearStandardFilters,
    standardGroupKey,
    isEditableGroup,
    isGroupCollapsed,
    toggleGroupCollapse,
    collapseAllGroups,
    expandAllGroups,
    standardStatusLabel,
    standardStatusClass,
    load,
    onFilterRouteChange,
    onStandardRouteChange,
    onStandardRouteVersionChange,
    openStandardGroup,
    isEmptyValue,
    copyStandardValues,
    fillEmptyRowsWithDefaults,
    applyFirstEnabledRowToAll,
    copyPreviousRow,
    saveStandard,
    deactivateStandard,
    routeSeqLabel
  }
}
