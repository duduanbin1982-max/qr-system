// useApprovalConfig.js — Approval Config Composable
import { ref, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useApprovalConfig() {
  const approvalConfigs = ref([])
  const approvalConfigLoading = ref(false)
  const approvalConfigSaving = ref(false)
  const approvalProcesses = ref([])
  const roleOptions = ref([])
  const globalApprovalEnabled = ref(true)
  const policyRevision = ref(null)
  const dirtyProcessIds = ref(new Set())

  async function loadApprovalConfig() {
    approvalConfigLoading.value = true
    try {
      const d = await api.domains.approvals.approvalConfig()
      roleOptions.value = d.role_options || []
      const roleIdByCode = Object.fromEntries(roleOptions.value.map(role => [role.code, role.id]))
      approvalConfigs.value = (d.configs || []).map(item => ({
        ...item,
        approver_role_id: item.approver_role_id || roleIdByCode[item.approver_role] || null,
        approver_role_2_id: item.approver_role_2_id || roleIdByCode[item.approver_role_2] || '',
        approver_role_3_id: item.approver_role_3_id || roleIdByCode[item.approver_role_3] || '',
      }))
      dirtyProcessIds.value = new Set()
      globalApprovalEnabled.value = d.global_approval_enabled !== false
      const policies = await api.domains.approvals.approvalPolicies()
      policyRevision.value = policies.policies?.[0]?.version || null
    } catch(e) { showToast('加载审批配置失败', 'error') }
    finally { approvalConfigLoading.value = false }
  }
  async function loadApprovalProcesses() {
    try {
      const d = await api.domains.processes.listProcesses({ limit: 500 })
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
  function configFor(processId) {
    return approvalConfigs.value.find(item => item.process_id === processId) || {}
  }
  function markDirty(processId) {
    dirtyProcessIds.value = new Set([...dirtyProcessIds.value, processId])
  }
  async function toggleApproval(processId) {
    const current = isApprovalRequired(processId)
    const config = approvalConfigs.value.find(item => item.process_id === processId)
    if (!config) return
    config.require_approval = current ? 0 : 1
    markDirty(processId)
  }
  async function saveApprovalChanges() {
    if (!dirtyProcessIds.value.size) return
    approvalConfigSaving.value = true
    try {
      const roleById = id => roleOptions.value.find(role => role.id === Number(id))
      const configs = approvalConfigs.value
        .filter(item => dirtyProcessIds.value.has(item.process_id))
        .map(item => {
          const level = Number(item.approval_level || 1)
          return {
            process_id: item.process_id,
            require_approval: item.require_approval ? 1 : 0,
            approval_level: level,
            approver_role: roleById(item.approver_role_id)?.code || item.approver_role || 'admin',
            approver_role_2: level >= 2 ? (roleById(item.approver_role_2_id)?.code || item.approver_role_2 || '') : '',
            approver_role_3: level >= 3 ? (roleById(item.approver_role_3_id)?.code || item.approver_role_3 || '') : '',
            ...(item.approver_role_id ? { approver_role_id: Number(item.approver_role_id) } : {}),
            ...(level >= 2 && item.approver_role_2_id ? { approver_role_2_id: Number(item.approver_role_2_id) } : {}),
            ...(level >= 3 && item.approver_role_3_id ? { approver_role_3_id: Number(item.approver_role_3_id) } : {}),
          }
        })
      await api.domains.approvals.saveApprovalConfig({ configs })
      await loadApprovalConfig()
      showToast('审批配置已保存')
    } catch(e) { showToast(e.message, 'error') }
    finally { approvalConfigSaving.value = false }
  }

  onMounted(() => { loadApprovalConfig(); loadApprovalProcesses() })

  return {
    approvalConfigs, approvalConfigLoading, approvalConfigSaving, approvalProcesses, roleOptions,
    globalApprovalEnabled, policyRevision, dirtyProcessIds,
    loadApprovalConfig, loadApprovalProcesses, approvalSet, isApprovalRequired,
    configFor, markDirty, toggleApproval, saveApprovalChanges,
  }
}
