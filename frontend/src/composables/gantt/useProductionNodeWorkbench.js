import { computed, ref } from 'vue'

export const PRODUCTION_NODE_TABS = Object.freeze([
  { key: 'list', label: '节点列表' },
  { key: 'editor', label: '节点编辑' },
  { key: 'calendar', label: '工作日历' },
  { key: 'capabilities', label: '能力限制' },
])

export function useProductionNodeWorkbench({
  nodes,
  onEnterTab = () => {},
  onSelectNode = () => {},
  onClose = () => {},
}) {
  const activeTab = ref('list')
  const selectedNodeId = ref(null)
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

  function requestTransition(transition) {
    if (!isDirty.value) {
      transition()
      return true
    }
    pendingTransition.value = transition
    showDiscardConfirm.value = true
    return false
  }

  function requestTab(tab) {
    return requestTransition(() => {
      activeTab.value = tab
      onEnterTab(tab, selectedNode.value)
    })
  }

  function requestNode(node) {
    return requestTransition(() => {
      selectedNodeId.value = node?.id ?? null
      onSelectNode(node || null)
    })
  }

  function requestClose() {
    return requestTransition(() => onClose())
  }

  function confirmDiscard() {
    isDirty.value = false
    showDiscardConfirm.value = false
    const transition = pendingTransition.value
    pendingTransition.value = null
    transition?.()
  }

  function cancelDiscard() {
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
    markDirty,
  }
}
