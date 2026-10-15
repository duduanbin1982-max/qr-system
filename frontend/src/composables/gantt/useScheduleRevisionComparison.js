import { computed, ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useScheduleRevisionComparison() {
  const revisionDialog = ref(false)
  const revisionLoading = ref(false)
  const revisionHistory = ref([])
  const revisionDetail = ref(null)
  const previousRevisionDetail = ref(null)

  function parsedItem(item) {
    let payload = {}
    try {
      payload = JSON.parse(item.payload_json || '{}')
    } catch {
      payload = {}
    }
    return { ...payload, ...item }
  }

  const revisionDifferences = computed(() => {
    if (revisionDetail.value?.replan_differences?.length) {
      return revisionDetail.value.replan_differences.map(item => ({
        key: `replan:${item.id || item.order_process_id}`,
        process: `订单工序 #${item.order_process_id}`,
        type: item.change_type || '动态重排',
        before: item.before || {},
        after: item.after || {},
      }))
    }
    const before = new Map((previousRevisionDetail.value?.items || []).map(item => {
      const normalized = parsedItem(item)
      return [String(normalized.order_process_id), normalized]
    }))
    const after = new Map((revisionDetail.value?.items || []).map(item => {
      const normalized = parsedItem(item)
      return [String(normalized.order_process_id), normalized]
    }))
    return [...new Set([...before.keys(), ...after.keys()])].map((key) => {
      const left = before.get(key) || {}
      const right = after.get(key) || {}
      const fields = ['production_node_id', 'planned_start_at', 'planned_end_at', 'quantity', 'occupied_minutes', 'status']
      const changed = fields.filter(field => String(left[field] ?? '') !== String(right[field] ?? ''))
      return {
        key: `compare:${key}`,
        process: right.process_name_snapshot || left.process_name_snapshot || `订单工序 #${key}`,
        type: !left.order_process_id ? '新增' : !right.order_process_id ? '移除' : changed.length ? changed.join('、') : '无变化',
        before: left,
        after: right,
      }
    }).filter(item => item.type !== '无变化')
  })

  async function loadRevision(revisionId) {
    if (!revisionId) return
    revisionLoading.value = true
    try {
      revisionDetail.value = await api.domains.production.getScheduleRevision(revisionId, { limit: 1000 })
      const revisionNo = Number(revisionDetail.value?.revision?.revision_no || 0)
      const previous = revisionHistory.value.find(item => Number(item.revision_no) < revisionNo)
      previousRevisionDetail.value = previous
        ? await api.domains.production.getScheduleRevision(previous.id, { limit: 1000 })
        : null
    } catch (error) {
      showToast(error.message || '加载排程版本失败', 'error')
    } finally {
      revisionLoading.value = false
    }
  }

  async function openRevision(card) {
    revisionDialog.value = true
    revisionLoading.value = true
    revisionDetail.value = null
    previousRevisionDetail.value = null
    try {
      const history = await api.domains.production.listOrderScheduleRevisions(card.orderId, { limit: 100 })
      revisionHistory.value = history.revisions || []
      await loadRevision(card.revisionId)
    } catch (error) {
      showToast(error.message || '加载排程版本失败', 'error')
      revisionLoading.value = false
    }
  }

  return {
    revisionDialog,
    revisionLoading,
    revisionHistory,
    revisionDetail,
    revisionDifferences,
    loadRevision,
    openRevision,
  }
}
