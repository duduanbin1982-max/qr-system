// useProcessConfig.js
import { ref, reactive, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useProcessConfig() {
  const processConfig = reactive({})
  const processConfigLoading = ref(false)
  const processConfigSaving = ref(false)

  async function loadProcessConfig() {
    processConfigLoading.value = true
    try {
      const d = await api.getSettings()
      const s = d.settings || {}
      Object.assign(processConfig, {
        process_order_mode: s.process_order_mode || 'sequential',
        delivery_warning_days: parseInt(s.delivery_warning_days) || 7,
        limit_by_prev_process: s.limit_by_prev_process || '1',
        limit_by_order_qty: s.limit_by_order_qty || '1',
        page_size: parseInt(s.page_size) || 20,
        approval_enabled: s.approval_enabled || '0',
        auto_order_no: s.auto_order_no || '',
      })
    } catch(e) { showToast(e.message, 'error') }
    finally { processConfigLoading.value = false }
  }

  async function saveProcessConfig() {
    processConfigSaving.value = true
    try {
      const payload = {
        process_order_mode: processConfig.process_order_mode,
        delivery_warning_days: String(processConfig.delivery_warning_days),
        limit_by_prev_process: processConfig.limit_by_prev_process,
        limit_by_order_qty: processConfig.limit_by_order_qty,
        page_size: String(processConfig.page_size),
        approval_enabled: processConfig.approval_enabled,
        auto_order_no: processConfig.auto_order_no,
      }
      await api.saveSettings(payload)
      showToast('保存成功')
    } catch(e) { showToast(e.message, 'error') }
    finally { processConfigSaving.value = false }
  }

  onMounted(() => { loadProcessConfig() })

  return {
    processConfig, processConfigLoading, processConfigSaving,
    loadProcessConfig, saveProcessConfig,
  }
}