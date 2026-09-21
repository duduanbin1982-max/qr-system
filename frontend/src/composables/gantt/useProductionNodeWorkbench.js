import { computed, ref } from 'vue'

export const PRODUCTION_NODE_TABS = Object.freeze([
  { key: 'list', label: '节点列表' },
  { key: 'editor', label: '节点编辑' },
  { key: 'calendar', label: '工作日历' },
  { key: 'capabilities', label: '能力限制' },
])

export function useProductionNodeWorkbench({
  nodes,
  selectedNodeId: controlledSelectedNodeId = null,
  onEnterTab = () => {},
  onSelectNode = () => {},
  onClose = () => {},
  onDiscard = () => {},
}) {
  const activeTab = ref('list')
  const localSelectedNodeId = ref(null)
  const selectedNodeId = controlledSelectedNodeId || localSelectedNodeId
  const search = ref('')
  const statusFilter = ref('')
  const isDirty = ref(false)
  const showDiscardConfirm = ref(false)
  const pendingTransition = ref(null)

  const selectedNode = computed(() => (
    nodes.value.find(node => String(node.id) === String(selectedNodeId.value)) || null
  ))

  const filteredGroups = computed(() => {
    const query = search.value.trim().toLocaleLowerCase()
    const groups = new Map()
    for (const node of nodes.value) {
      if (statusFilter.value && node.status !== statusFilter.value) continue
      const haystack = [node.node_code, node.node_name, node.process_name]
        .filter(Boolean).join(' ').toLocaleLowerCase()
      if (query && !haystack.includes(query)) continue
      const key = String(node.process_id)
      if (!groups.has(key)) {
        groups.set(key, {
          process_id: node.process_id,
          process_name: node.process_name || '未命名工序',
          nodes: [],
        })
      }
      groups.get(key).nodes.push(node)
    }
    return [...groups.values()]
  })

  function commitNode(node) {
    if (!controlledSelectedNodeId) localSelectedNodeId.value = node?.id ?? null
    return onSelectNode(node || null)
  }

  function runTransition(transition) {
    if (!isDirty.value) {
      return transition()
    }
    pendingTransition.value = transition
    showDiscardConfirm.value = true
    return false
  }

  function requestTransition(transition) {
    return runTransition(transition)
  }

  function requestTab(tab) {
    if (activeTab.value === tab) return true
    return runTransition(() => {
      activeTab.value = tab
      return onEnterTab(tab, selectedNode.value)
    })
  }

  function requestNode(node) {
    return runTransition(() => commitNode(node))
  }

  function requestClose() {
    return runTransition(() => onClose())
  }

  function finishTransition(transition) {
    const rollback = onDiscard(activeTab.value, selectedNode.value)
    if (rollback && typeof rollback.then === 'function') {
      return rollback.then(() => transition?.())
    }
    return transition?.()
  }

  function confirmDiscard() {
    const transition = pendingTransition.value
    pendingTransition.value = null
    showDiscardConfirm.value = false
    isDirty.value = false
    return finishTransition(transition)
  }

  function cancelDiscard() {
    showDiscardConfirm.value = false
    pendingTransition.value = null
  }

  function resetSession() {
    activeTab.value = 'list'
    selectedNodeId.value = null
    search.value = ''
    statusFilter.value = ''
    isDirty.value = false
    showDiscardConfirm.value = false
    pendingTransition.value = null
  }

  function markDirty(value = true) {
    isDirty.value = Boolean(value)
  }

  return {
    activeTab,
    selectedNodeId,
    selectedNode,
    search,
    statusFilter,
    filteredGroups,
    isDirty,
    showDiscardConfirm,
    requestTransition,
    requestTab,
    requestNode,
    requestClose,
    confirmDiscard,
    cancelDiscard,
    resetSession,
    markDirty,
  }
}
