import { computed, reactive, ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { formatUnitPrice as unitPrice } from '@/composables/wage/payrollFormat.js'

export function useHistoricalPriceConfirmation(props, emit) {
  const selectedReview = ref(null)

  const referenceCandidate = ref(null)

  const editorOpen = ref(false)

  const busy = ref(false)

  const form = reactive(emptyForm())

  const orderSummary = computed(() => (selectedReview.value?.affected_orders || []).map(order => `${order.order_no}${order.product_code ? ` · ${order.product_code}` : ''}`).join('、'))

  const routeSummary = computed(() => `${selectedReview.value?.route?.name || '-'} · V${selectedReview.value?.route?.version || '-'}`)

  const processSummary = computed(() => `${selectedReview.value?.process?.name || '-'} · V${selectedReview.value?.process?.version || '-'}`)

  function emptyForm() { const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset()); return { normal_unit_price: '', valid_from: now.toISOString().slice(0, 16), valid_to: '', rework_rate_percent: '', confirmation_reason: '' } }

  function commandKey(prefix) { const uuid = globalThis.crypto?.randomUUID?.(); return `${prefix}:${uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`}` }

  function timestamp(value) { const normalized = String(value || '').replace('T', ' '); return normalized.length === 16 ? `${normalized}:00` : normalized }

  function openCreate(review, candidate = null) { selectedReview.value = review; referenceCandidate.value = candidate; Object.assign(form, emptyForm()); if (candidate) { form.normal_unit_price = (Number(candidate.normal_unit_price_micros || 0) / 10000).toFixed(4); form.valid_from = String(candidate.valid_from || form.valid_from).replace(' ', 'T').slice(0, 16); form.rework_rate_percent = candidate.rework_rate_configured ? (Number(candidate.rework_rate_basis_points || 0) / 100).toFixed(2) : '' } editorOpen.value = true }

  function closeEditor() { if (!busy.value) editorOpen.value = false }

  function draftFor(review) { return (review?.drafts || []).find(draft => draft.status === 'draft') || null }

  function formatDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '-' }

  async function createDraft() { const amount = Number(form.normal_unit_price); if (!Number.isFinite(amount) || amount <= 0) return showToast('请填写有效的正常工价', 'error'); if (form.confirmation_reason.length < 2) return showToast('请填写至少 2 个字符的确认理由', 'error'); if (form.rework_rate_percent && (Number(form.rework_rate_percent) < 0 || Number(form.rework_rate_percent) > 100)) return showToast('返工倍率必须在 0% 到 100% 之间', 'error'); busy.value = true; try { await api.domains.wages.createHistoricalPriceManualDraft(selectedReview.value.review_id, { normal_unit_price: String(form.normal_unit_price), rework_rate_configured: Boolean(form.rework_rate_percent), rework_rate_percent: form.rework_rate_percent ? Number(form.rework_rate_percent) : 0, valid_from: timestamp(form.valid_from), valid_to: form.valid_to ? timestamp(form.valid_to) : null, confirmation_reason: form.confirmation_reason, idempotency_key: commandKey(`historical-price-draft:${selectedReview.value.review_id}`) }); showToast('人工确认草稿已保存，请交由另一位批准人审核'); editorOpen.value = false; emit('refresh') } catch (error) { showToast(error.message || '保存人工工价草稿失败', 'error') } finally { busy.value = false } }

  async function voidDraft(draft) { const reason = window.prompt('请输入作废原因'); if (!reason || reason.trim().length < 2) return; busy.value = true; try { await api.domains.wages.voidHistoricalPriceManualDraft(draft.id, { row_version: Number(draft.row_version), reason: reason.trim(), idempotency_key: commandKey(`historical-price-void:${draft.id}`) }); showToast('人工工价草稿已作废'); emit('refresh') } catch (error) { showToast(error.message || '作废草稿失败', 'error') } finally { busy.value = false } }

  async function approveDraft(draft) { if (!window.confirm('确认独立批准这条历史工价？')) return; busy.value = true; try { await api.domains.wages.approveHistoricalPriceManualDraft(draft.id, { row_version: Number(draft.row_version), idempotency_key: commandKey(`historical-price-approve:${draft.id}`) }); showToast('历史精确工价已批准'); emit('refresh') } catch (error) { showToast(error.message || '批准历史工价失败', 'error') } finally { busy.value = false } }

  return {
    selectedReview,
    referenceCandidate,
    editorOpen,
    busy,
    form,
    orderSummary,
    routeSummary,
    processSummary,
    emptyForm,
    commandKey,
    timestamp,
    openCreate,
    closeEditor,
    draftFor,
    unitPrice,
    formatDate,
    createDraft,
    voidDraft,
    approveDraft
  }
}
