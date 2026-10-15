import { computed, reactive, ref, watch } from 'vue'
import { showToast } from '@/lib/store.js'
import { useRoutePriceVersions } from '@/composables/useRoutePriceVersions.js'

export function usePriceVersionEditor(props, emit) {
  const { busy, createDraft, voidDraft } = useRoutePriceVersions()

  const voidReason = ref('')

  const form = reactive(emptyForm())

  const isPending = computed(
    () => props.reference?.route_version_status === 'pending_approval'
  )

  const inputMicros = computed(
    () => Math.round(Number(form.normal_unit_price || 0) * 10000)
  )

  const inputPrice = computed(() => unitPrice(inputMicros.value))

  const priceDifference = computed(() => props.currentPrice
    ? inputMicros.value - Number(props.currentPrice.normal_unit_price_micros || 0)
    : null)

  const changeText = computed(() => {
    if (priceDifference.value === null) return '首次设置'
    if (priceDifference.value === 0) return '价格不变'
    const sign = priceDifference.value > 0 ? '+' : '-'
    return `${sign}${unitPrice(Math.abs(priceDifference.value))}`
  })

  const changeClass = computed(() => priceDifference.value > 0
    ? 'change-up'
    : priceDifference.value < 0 ? 'change-down' : '')

  function localNow() {
    const date = new Date()
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
    return date.toISOString().slice(0, 16)
  }

  function emptyForm() {
    return {
      normal_unit_price: '',
      valid_from: localNow(),
      rework_rate_configured: false,
      rework_rate_percent: '',
      remark: '',
    }
  }

  function reset() {
    Object.assign(form, emptyForm())
    voidReason.value = ''
    const source = props.draftPrice || props.currentPrice
    if (!source) return
    form.normal_unit_price = (
      Number(source.normal_unit_price_micros || 0) / 10000
    ).toFixed(4)
    form.valid_from = String(source.valid_from || localNow()).replace(' ', 'T').slice(0, 16)
    form.rework_rate_configured = Boolean(source.rework_rate_configured)
    form.rework_rate_percent = source.rework_rate_configured
      ? (Number(source.rework_rate_basis_points || 0) / 100).toFixed(2)
      : ''
    form.remark = source.remark || ''
  }

  function unitPrice(value) {
    return `¥${(Number(value || 0) / 10000).toFixed(4)}`
  }

  function formatDateTime(value) {
    return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
  }

  function closeEditor() {
    if (!busy.value) emit('close')
  }

  async function submitCreate() {
    const amount = Number(form.normal_unit_price)
    if (!Number.isFinite(amount) || amount <= 0 || !form.valid_from) {
      showToast('请填写有效的正常工价和生效时间', 'error')
      return
    }
    if (form.rework_rate_configured) {
      const rate = Number(form.rework_rate_percent)
      if (!Number.isFinite(rate) || rate < 0 || rate > 100) {
        showToast('返工倍率必须在 0% 到 100% 之间', 'error')
        return
      }
    }
    try {
      const result = await createDraft(form, props.reference)
      showToast('工价草稿已创建')
      emit('created', result)
    } catch (error) {
      showToast(error.message || '创建工价草稿失败', 'error')
    }
  }

  async function submitVoid() {
    if (voidReason.value.length < 2) {
      showToast('请填写至少 2 个字符的作废原因', 'error')
      return
    }
    try {
      const result = await voidDraft(props.draftPrice, voidReason.value)
      showToast('工价草稿已作废')
      emit('voided', result)
    } catch (error) {
      showToast(error.message || '作废工价草稿失败', 'error')
    }
  }

  watch(
    () => [props.open, props.reference?.reference_key, props.draftPrice?.id],
    reset,
    { immediate: true }
  )

  return {
    busy,
    createDraft,
    voidDraft,
    voidReason,
    form,
    isPending,
    inputMicros,
    inputPrice,
    priceDifference,
    changeText,
    changeClass,
    localNow,
    emptyForm,
    reset,
    unitPrice,
    formatDateTime,
    closeEditor,
    submitCreate,
    submitVoid
  }
}
