// useCompanyInfo.js — Company Info Composable
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export const COMPANY_INFO_FIELDS = ['company_name', 'contact', 'phone', 'address', 'description']

function emptyCompanyInfo() {
  return Object.fromEntries(COMPANY_INFO_FIELDS.map(field => [field, '']))
}

export function useCompanyInfo() {
  const settings = ref(emptyCompanyInfo())
  const edits = ref(emptyCompanyInfo())
  const version = ref(0)
  const updatedAt = ref('')
  const updatedByName = ref('')
  const revisions = ref([])
  const historyRedacted = ref(true)
  const loading = ref(true)
  const historyLoading = ref(true)
  const saving = ref(false)
  const conflict = ref(false)
  const canEdit = computed(() => can('company_info:edit'))
  const canAuditHistory = computed(() => can('company_info:audit_history'))

  const companyInfoDirty = computed(() =>
    COMPANY_INFO_FIELDS.some(field => edits.value[field] !== settings.value[field])
  )

  function applyProfile(profile) {
    const next = Object.fromEntries(
      COMPANY_INFO_FIELDS.map(field => [field, profile?.[field] || ''])
    )
    settings.value = next
    edits.value = { ...next }
    version.value = profile?.version || 0
    updatedAt.value = profile?.updated_at || ''
    updatedByName.value = profile?.updated_by_name || ''
    conflict.value = false
  }

  async function loadSettings() {
    loading.value = true
    try {
      const data = await api.domains.settings.getCompanyInfo()
      applyProfile(data.profile)
    } catch(e) { showToast(e.message, 'error') }
    finally { loading.value = false }
  }

  async function loadHistory() {
    historyLoading.value = true
    try {
      const data = await api.domains.settings.getCompanyInfoHistory()
      revisions.value = data.revisions || []
      historyRedacted.value = !data.sensitive_history_visible
    } catch(e) { showToast(e.message, 'error') }
    finally { historyLoading.value = false }
  }

  async function saveSettings() {
    if (!canEdit.value || !companyInfoDirty.value || saving.value) return false
    saving.value = true
    try {
      const payload = { version: version.value }
      for (const field of COMPANY_INFO_FIELDS) {
        if (edits.value[field] !== settings.value[field]) {
          payload[field] = edits.value[field]
        }
      }
      const data = await api.domains.settings.saveCompanyInfo(payload)
      applyProfile(data.profile)
      await loadHistory()
      showToast('保存成功')
      return true
    } catch(e) {
      if (e.status === 409 || e.code === 409) {
        conflict.value = true
        showToast('公司资料已被其他用户更新，请刷新后重新编辑', 'error')
      } else {
        showToast(e.message, 'error')
      }
      return false
    }
    finally { saving.value = false }
  }

  function discardChanges() {
    edits.value = { ...settings.value }
    conflict.value = false
  }

  async function reloadAfterConflict() {
    await loadSettings()
    await loadHistory()
  }

  function handleBeforeUnload(event) {
    if (!companyInfoDirty.value) return
    event.preventDefault()
    event.returnValue = ''
  }

  onMounted(() => {
    window.addEventListener('beforeunload', handleBeforeUnload)
    Promise.all([loadSettings(), loadHistory()])
  })
  onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))

  return {
    settings, edits, version, updatedAt, updatedByName, revisions,
    loading, historyLoading, saving, conflict, historyRedacted,
    canEdit, canAuditHistory, companyInfoDirty,
    loadSettings, loadHistory, saveSettings, discardChanges, reloadAfterConflict,
    hasUnsavedChanges: () => companyInfoDirty.value,
  }
}
