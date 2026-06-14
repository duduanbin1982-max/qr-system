// useApprovalConfig.js — Approval Config Composable
import { ref, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useApprovalConfig() {
  const approvalConfigs = ref([])
  const approvalConfigLoading = ref(false)
  const approvalConfigSaving = ref(false)
  const approvalProcesses = ref([])

  async function loadApprovalConfig() {
    approvalConfigLoading.value = true
    try {
      const d = await api.get('/api/approvals/config')
      approvalConfigs.value = d.configs || []
    } catch(e) { showToast('加载审批配置失败', 'error') }
    finally { approvalConfigLoading.value = false }
  }
  async function loadApprovalProcesses() {
    try {
      const d = await api.get('/api/processes?limit=500')
      approvalProcesses.value = d.processes || []
    } catch(e) { /* ignore */ }
  }
  const approvalSet = computed(() => {
    const s = new Set()
    for (const c of approvalConfigs.value) {
      if (c.require_approval === 1) s.add(c.process_id)
    }
    return s
  })
  function isApprovalRequired(processId) {
    return approvalSet.value.has(processId)
  }
  async function toggleApproval(processId) {
    const current = isApprovalRequired(processId)
    approvalConfigSaving.value = true
    try {
      await api.post('/api/approvals/config', {
        process_id: processId,
        require_approval: current ? 0 : 1
      })
      await loadApprovalConfig()
      showToast(current ? '已关闭审批' : '已开启审批')
    } catch(e) { showToast(e.message, 'error') }
    finally { approvalConfigSaving.value = false }
  }

  onMounted(() => { loadApprovalConfig(); loadApprovalProcesses() })

  return {
    approvalConfigs, approvalConfigLoading, approvalConfigSaving, approvalProcesses,
    loadApprovalConfig, loadApprovalProcesses, approvalSet, isApprovalRequired, toggleApproval,
  }
}
