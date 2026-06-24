// useCompanyInfo.js — Company Info Composable
import { ref, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useCompanyInfo() {
  const settings = ref({})
  const edits = ref({})
  const loading = ref(true)
  const saving = ref(false)

  const companyInfoDirty = computed(() =>
    JSON.stringify(edits.value) !== JSON.stringify(settings.value)
  )

  async function loadSettings() {
    loading.value = true
    try {
      const data = await api.getSettings()
      settings.value = data.settings || {}
      edits.value = { ...settings.value }
    } catch(e) { showToast(e.message, 'error') }
    finally { loading.value = false }
  }

  async function saveSettings() {
    saving.value = true
    try {
      const COMPANY_KEYS = ['company_name', 'contact', 'phone', 'address', 'description']
      const payload = {}
      for (const k of COMPANY_KEYS) {
        if (k in edits.value) payload[k] = edits.value[k]
      }
      await api.post('/api/settings/company-info', payload)
      showToast('保存成功')
      settings.value = { ...edits.value }
    } catch(e) { showToast(e.message, 'error') }
    finally { saving.value = false }
  }

  onMounted(() => { loadSettings() })

  return {
    settings, edits, loading, saving, companyInfoDirty,
    loadSettings, saveSettings,
  }
}