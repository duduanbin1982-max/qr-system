import { ref } from 'vue'

import { api } from '@/lib/api.js'


function commandKey(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  return `${prefix}:${uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

function timestamp(value) {
  const normalized = String(value || '').trim().replace('T', ' ')
  return normalized.length === 16 ? `${normalized}:00` : normalized
}

export function priceReferenceKey(reference) {
  return `${Number(reference.route_version_id)}:${Number(reference.process_version_id)}`
}

export function useRoutePriceVersions() {
  const references = ref([])
  const versions = ref([])
  const selectedReference = ref(null)
  const loading = ref(false)
  const busy = ref(false)
  const operationError = ref('')

  async function load() {
    loading.value = true
    operationError.value = ''
    try {
      const [versionData, referenceData] = await Promise.all([
        api.domains.wages.listRoutePriceVersions({}),
        api.domains.wages.getRoutePriceVersionReference({ include_pending: true }),
      ])
      versions.value = versionData.versions || []
      references.value = referenceData.items || []
      if (selectedReference.value) {
        const key = priceReferenceKey(selectedReference.value)
        selectedReference.value = references.value.find(
          item => priceReferenceKey(item) === key
        ) || null
      }
      return { references: references.value, versions: versions.value }
    } catch (error) {
      operationError.value = error.message || '工价版本加载失败'
      throw error
    } finally {
      loading.value = false
    }
  }

  function selectReference(referenceOrKey) {
    const key = typeof referenceOrKey === 'string'
      ? referenceOrKey
      : priceReferenceKey(referenceOrKey)
    selectedReference.value = references.value.find(
      item => priceReferenceKey(item) === key
    ) || (typeof referenceOrKey === 'object' ? referenceOrKey : null)
    return selectedReference.value
  }

  async function createDraft(form, lockedReference = selectedReference.value) {
    const reference = lockedReference
    if (!reference) throw new Error('未选择精确路线工序版本')
    busy.value = true
    operationError.value = ''
    try {
      const payload = {
        route_id: Number(reference.route_id),
        route_version_id: Number(reference.route_version_id),
        process_id: Number(reference.process_id),
        process_version_id: Number(reference.process_version_id),
        expected_route_content_digest: reference.route_content_digest,
        expected_process_content_digest: reference.process_content_digest,
        normal_unit_price: String(form.normal_unit_price),
        valid_from: timestamp(form.valid_from),
        remark: String(form.remark || '').trim(),
        idempotency_key: commandKey('route-price-create'),
      }
      if (form.rework_rate_configured) {
        payload.rework_rate_basis_points = Math.round(
          Number(form.rework_rate_percent) * 100
        )
      }
      return await api.domains.wages.createRoutePriceVersion(payload)
    } catch (error) {
      operationError.value = error.message || '创建工价草稿失败'
      throw error
    } finally {
      busy.value = false
    }
  }

  async function voidDraft(price, reason) {
    if (!price?.id) throw new Error('未选择待作废工价草稿')
    busy.value = true
    operationError.value = ''
    try {
      return await api.domains.wages.voidRoutePriceVersion(price.id, {
        row_version: Number(price.row_version),
        reason: String(reason || '').trim(),
        idempotency_key: commandKey('route-price-void'),
      })
    } catch (error) {
      operationError.value = error.message || '作废工价草稿失败'
      throw error
    } finally {
      busy.value = false
    }
  }

  return {
    references,
    versions,
    selectedReference,
    loading,
    busy,
    operationError,
    load,
    selectReference,
    createDraft,
    voidDraft,
  }
}
