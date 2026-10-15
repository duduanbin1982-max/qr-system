import { nextTick, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'

export function useWorkTimeWorkspace() {
  const tabs = [
    { key: 'standards', label: '标准工时' },
    { key: 'records', label: '工时流水' },
    { key: 'audit', label: '工时审核' },
  ]

  const activeTab = ref(localStorage.getItem('workTimeTab') || 'standards')

  const keyword = ref('')

  const stats = ref({})

  const processRoutes = ref([])

  const processes = ref([])

  const users = ref([])

  const standardsPanel = ref(null)

  const recordsPanel = ref(null)

  const auditPanel = ref(null)

  const showReviewModal = ref(false)

  const reviewRecord = ref(null)

  async function loadStats() {
    try { stats.value = await api.domains.workTime.workTimeStats() } catch (error) { stats.value = {} }
  }

  async function loadRefs() {
    try {
      const result = await api.domains.processRoutes.listProcessRoutes({ limit: 500 })
      processRoutes.value = result.routes || result.items || []
    } catch (error) { processRoutes.value = [] }
    try {
      const result = await api.domains.processes.listProcesses({ limit: 500 })
      processes.value = result.processes || result.items || []
    } catch (error) { processes.value = [] }
    try {
      const result = await api.domains.users.listUsers({ limit: 200, status: 'active' })
      users.value = result.users || result.items || []
    } catch (error) { users.value = [] }
  }

  function currentPanel() {
    if (activeTab.value === 'standards') return standardsPanel.value
    if (activeTab.value === 'records') return recordsPanel.value
    if (activeTab.value === 'audit') return auditPanel.value
    return null
  }

  async function loadActive() {
    await nextTick()
    const panel = currentPanel()
    if (panel?.load) await panel.load()
    await loadStats()
  }

  async function switchTab(key) {
    activeTab.value = key
    localStorage.setItem('workTimeTab', key)
    await loadActive()
  }

  function openPrimaryAction() {
    if (activeTab.value === 'standards') standardsPanel.value?.openStandardGroup()
    if (activeTab.value === 'records') recordsPanel.value?.openRecord()
  }

  async function handlePanelChanged() {
    await loadStats()
  }

  function openReview(row) {
    reviewRecord.value = row
    showReviewModal.value = true
  }

  async function handleReviewSaved() {
    await loadActive()
  }

  onMounted(async () => {
    await loadRefs()
    await loadActive()
  })

  return {
    tabs,
    activeTab,
    keyword,
    stats,
    processRoutes,
    processes,
    users,
    standardsPanel,
    recordsPanel,
    auditPanel,
    showReviewModal,
    reviewRecord,
    loadStats,
    loadRefs,
    currentPanel,
    loadActive,
    switchTab,
    openPrimaryAction,
    handlePanelChanged,
    openReview,
    handleReviewSaved
  }
}
