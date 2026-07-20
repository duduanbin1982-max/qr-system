import { computed, ref } from 'vue'
import { api } from '@/lib/api.js'

function today() {
  return new Date().toISOString().slice(0, 10)
}

function positiveNumber(value) {
  const n = Number(value || 0)
  return Number.isFinite(n) ? n : 0
}

export function routeSeqLabel(seq) {
  return seq === null || seq === undefined || seq === '' ? '-' : Number(seq) + 1
}

export function useRouteWorkTimeStandards(processRoutesRef) {
  const standardRows = ref([])
  const enabledRowsCount = computed(() => standardRows.value.filter(row => row.enabled).length)

  function routeList() {
    return Array.isArray(processRoutesRef.value) ? processRoutesRef.value : []
  }

  function normalizeRouteProcesses(routeId) {
    const route = routeList().find(r => String(r.id) === String(routeId))
    return (route?.processes || []).map((item, index) => ({
      id: item.process_id || item.id,
      name: item.process_name || item.name || '',
      seq: item.seq_order ?? index,
      seqLabel: `${(item.seq_order ?? index) + 1}. `,
    })).filter(item => item.id)
  }

  async function fetchRouteStandardItems(routeId) {
    if (!routeId) return []
    try {
      const result = await api.domains.workTime.listWorkTimeStandardRoutes({ route_id: routeId, limit: 1 })
      return (result.route_groups && result.route_groups[0]?.items) || []
    } catch (error) {
      return []
    }
  }

  async function buildStandardRows(routeId, existingItems) {
    const routeProcesses = normalizeRouteProcesses(routeId)
    const routeStandards = existingItems || await fetchRouteStandardItems(routeId)
    const byProcess = new Map()
    ;(routeStandards || []).forEach(item => {
      if (!byProcess.has(String(item.process_id))) byProcess.set(String(item.process_id), item)
    })
    const sourceProcesses = routeProcesses.length ? routeProcesses : (routeStandards || []).map((item, index) => ({
      id: item.process_id,
      name: item.process_name || '',
      seq: item.route_seq_order ?? index,
    }))
    standardRows.value = sourceProcesses.map(proc => {
      const existing = byProcess.get(String(proc.id)) || {}
      return {
        id: existing.id || '',
        process_id: proc.id,
        process_name: proc.name,
        seq: proc.seq,
        enabled: existing.id ? existing.status !== 'inactive' : true,
        standard_minutes_per_unit: existing.standard_minutes_per_unit ?? '',
        setup_minutes: existing.setup_minutes ?? 0,
        difficulty_factor: existing.difficulty_factor ?? 1,
        remark: existing.remark || '',
      }
    })
  }

  function setAllStandardRows(enabled) {
    standardRows.value.forEach(row => { row.enabled = enabled })
  }

  function validateStandardRows() {
    if (!standardRows.value.length) return '该路线没有可维护的工序'
    const invalid = standardRows.value.find(row => row.enabled && positiveNumber(row.standard_minutes_per_unit) <= 0)
    return invalid ? `请填写「${invalid.process_name}」的单件标准工时` : ''
  }

  function buildSavePayload(routeId, effectiveFrom) {
    return {
      route_id: routeId,
      effective_from: effectiveFrom || today(),
      items: standardRows.value.map(row => ({
        id: row.id || undefined,
        process_id: row.process_id,
        enabled: row.enabled,
        status: row.enabled ? 'active' : 'inactive',
        standard_minutes_per_unit: positiveNumber(row.standard_minutes_per_unit),
        setup_minutes: positiveNumber(row.setup_minutes),
        difficulty_factor: positiveNumber(row.difficulty_factor) || 1,
        remark: row.remark || '',
      })),
    }
  }

  return {
    standardRows,
    enabledRowsCount,
    normalizeRouteProcesses,
    buildStandardRows,
    setAllStandardRows,
    validateStandardRows,
    buildSavePayload,
  }
}
