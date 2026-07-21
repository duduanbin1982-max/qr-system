import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


const defaultConfig = () => ({
  mode: 'soft',
  tail_percent: 70,
  reason_options: [],
  mode_options: [],
})


export function useCompletionFocus() {
  const showCompletionFocus = ref(false)
  const completionFocusLoading = ref(false)
  const completionFocusData = ref({ summary: {}, items: [] })
  const completionFocusConfig = ref(defaultConfig())
  const showFocusExceptionModal = ref(false)
  const focusExceptionOrder = ref(null)
  const focusExceptionForm = ref({ reason: '缺料', detail: '', expires_at: '' })

  function completionFocusModeOptions() {
    const options = completionFocusConfig.value.mode_options || []
    if (options.length) return options
    return [
      { value: 'off', label: '关闭', button_class: 'btn-primary' },
      { value: 'soft', label: '软提示', button_class: 'btn-warning' },
      { value: 'hard', label: '强拦截', button_class: 'btn-danger' },
    ]
  }

  function completionFocusModeLabel(mode) {
    return completionFocusModeOptions().find(item => item.value === mode)?.label || mode || ''
  }

  async function openCompletionFocus() {
    showCompletionFocus.value = true
    completionFocusLoading.value = true
    try {
      try {
        completionFocusConfig.value = await api.domains.orders.getCompletionFocusConfig()
      } catch {}
      completionFocusData.value = await api.domains.orders.getCompletionFocus({ limit: 120 })
      if (completionFocusData.value.config) {
        completionFocusConfig.value = completionFocusData.value.config
      }
    } catch (error) {
      completionFocusData.value = { summary: {}, items: [] }
      showToast(error.message || '加载集中完工看板失败', 'error')
    } finally {
      completionFocusLoading.value = false
    }
  }

  async function setCompletionFocusMode(mode) {
    try {
      const response = await api.domains.orders.saveCompletionFocusConfig({
        mode,
        tail_percent: completionFocusConfig.value.tail_percent || 70,
      })
      completionFocusConfig.value = response.config || { ...completionFocusConfig.value, mode }
      showToast(`集中完工模式已切换为：${completionFocusModeLabel(mode)}`)
      await openCompletionFocus()
    } catch (error) {
      showToast(error.message || '保存集中完工模式失败', 'error')
    }
  }

  function openFocusException(item) {
    focusExceptionOrder.value = item
    const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000)
    tomorrow.setMinutes(tomorrow.getMinutes() - tomorrow.getTimezoneOffset())
    focusExceptionForm.value = {
      reason: (completionFocusConfig.value.reason_options || ['缺料'])[0] || '缺料',
      detail: '',
      expires_at: tomorrow.toISOString().slice(0, 16),
    }
    showFocusExceptionModal.value = true
  }

  async function saveFocusException() {
    const order = focusExceptionOrder.value
    if (!order) return
    if (!focusExceptionForm.value.reason) { showToast('请选择例外原因', 'error'); return }
    try {
      await api.domains.orders.createCompletionFocusException(order.order_id, {
        ...focusExceptionForm.value,
        expires_at: (focusExceptionForm.value.expires_at || '').replace('T', ' '),
      })
      showToast('已设置例外订单')
      showFocusExceptionModal.value = false
      await openCompletionFocus()
    } catch (error) {
      showToast(error.message || '设置例外失败', 'error')
    }
  }

  async function cancelFocusException(item) {
    const exceptionId = item?.exception?.id
    if (!exceptionId) return
    if (!confirm('确认取消该订单的集中完工例外？')) return
    try {
      await api.domains.orders.cancelCompletionFocusException(exceptionId, { reason: '手动取消' })
      showToast('已取消例外')
      await openCompletionFocus()
    } catch (error) {
      showToast(error.message || '取消例外失败', 'error')
    }
  }

  return {
    showCompletionFocus, completionFocusLoading, completionFocusData, completionFocusConfig,
    showFocusExceptionModal, focusExceptionOrder, focusExceptionForm,
    openCompletionFocus, setCompletionFocusMode, completionFocusModeOptions,
    completionFocusModeLabel, openFocusException, saveFocusException, cancelFocusException,
  }
}
