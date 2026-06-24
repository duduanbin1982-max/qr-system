// useRoleManage.js
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { normalizeRolePermissions } from '@/lib/permissions.js'

export function useRoleManage() {
  const roles = ref([])
  const groups = ref([])
  const roleLoading = ref(false)
  const showRoleModal = ref(false)
  const roleModalEdit = ref(false)
  const roleForm = reactive({ name:'', code:'', description:'', group_id:null, parent_id:null, level:1, permissions:'', status:'active' })
  const allPermissions = ref([])
  const selectedPerms = ref([])
  const permissionTree = ref([])
  const permissionCodes = ref([])
  const permissionLabelMap = ref({})
  const permissionSearch = ref('')
  const permissionExpanded = ref([])
  const wildcardSelected = ref(false)
  const permActionLabels = [
    { key:'view', label:'查看' }, { key:'create', label:'创建' },
    { key:'edit', label:'编辑' }, { key:'delete', label:'删除' },
    { key:'manage', label:'管理' }, { key:'export', label:'导出' },
  ]
  const roleSearch = ref('')
  const roleAddGroup = ref(null)

  const filteredRoles = computed(() => {
    let list = roles.value
    const kw = roleSearch.value.trim().toLowerCase()
    if (kw) list = list.filter(r => (r.name||'').toLowerCase().includes(kw) || (r.code||'').toLowerCase().includes(kw))
    if (roleAddGroup.value) list = list.filter(r => r.group_id === roleAddGroup.value)
    return list
  })

  async function loadRoles() {
    roleLoading.value = true
    try { const d = await api.listRoles(); roles.value = d.roles||[] }
    catch(e) { showToast(e.message,'error') }
    finally { roleLoading.value = false }
  }
  async function loadGroups() {
    try { const d = await api.listRoleGroups(); groups.value = d.role_groups||[] }
    catch(e) { groups.value = [] }
  }
  async function loadPermissions() {
    try {
      const d = await api.get('/api/permissions')
      allPermissions.value = d.permissions || []
      permissionTree.value = d.mergedTree || d.merged_tree || d.tree || []
      permissionCodes.value = d.codes || collectTreeCodes(permissionTree.value)
      permissionLabelMap.value = buildPermissionLabelMap(permissionTree.value)
      if (wildcardSelected.value) selectedPerms.value = [...permissionCodes.value]
      if (!permissionExpanded.value.length) expandPermissionTree()
    }
    catch(e) {
      allPermissions.value = []
      permissionTree.value = []
      permissionCodes.value = []
      permissionLabelMap.value = {}
    }
  }
  const groupMap = computed(() => {
    const m = {}
    for (const g of groups.value) { m[g.id] = g.name }
    return m
  })
  function getGroupName(gid) {
    return groupMap.value[gid] || '未分组'
  }
  function formatPerms(permsStr) {
    try {
      const p = JSON.parse(permsStr||'[]')
      if (!Array.isArray(p)) return [permsStr]
      if (p.includes('*')) return ['全部权限（*）']
      return p.map(code => permissionLabelMap.value[code] || code)
    }
    catch { return permsStr ? [permsStr] : [] }
  }
  function openAddRole() {
    roleModalEdit.value = false
    Object.assign(roleForm, { name:'', code:'', description:'', group_id:roleAddGroup.value, parent_id:null, level:1, permissions:'[]', status:'active' })
    selectedPerms.value = []
    wildcardSelected.value = false
    showRoleModal.value = true
  }
  function expandStarPerms(perms) {
    if (!Array.isArray(perms)) return perms
    if (perms.includes('*')) {
      wildcardSelected.value = true
      return [...permissionCodes.value]
    }
    wildcardSelected.value = false
    return normalizeRolePermissions(perms)
  }
  function openEditRole(role) {
    roleModalEdit.value = true
    Object.assign(roleForm, { name:role.name, code:role.code, description:role.description||'', group_id:role.group_id, parent_id:role.parent_id, level:role.level||1, permissions:role.permissions||'[]', status:role.status||'active' })
    roleForm._id = role.id
    try { selectedPerms.value = expandStarPerms(JSON.parse(role.permissions || '[]')) }
    catch { selectedPerms.value = [] }
    showRoleModal.value = true
  }
  async function saveRole() {
    if (!roleForm.name) { showToast('角色名称不能为空','error'); return }
    roleForm.permissions = JSON.stringify(wildcardSelected.value ? ['*'] : normalizeRolePermissions(selectedPerms.value))
    try {
      const body = { ...roleForm }; delete body._id
      if (roleModalEdit.value) await api.updateRole(roleForm._id, body)
      else await api.createRole(body)
      showToast(roleModalEdit.value?'更新成功':'创建成功')
      showRoleModal.value = false
      loadRoles()
    } catch(e) { showToast(e.message,'error') }
  }
  async function deleteRole(rid) {
    if (!confirm('确定删除该角色？')) return
    try { await api.deleteRole(rid); showToast('删除成功'); loadRoles() }
    catch(e) { showToast(e.message,'error') }
  }

  function collectTreeCodes(nodes) {
    const codes = []
    for (const node of nodes || []) {
      if (node.code) codes.push(node.code)
      for (const operation of node.operations || []) {
        if (operation.code) codes.push(operation.code)
      }
      codes.push(...collectTreeCodes(node.children || []))
    }
    return Array.from(new Set(codes))
  }

  function collectTreeKeys(nodes) {
    const keys = []
    for (const node of nodes || []) {
      const key = node.key || node.code || node.label
      if (key) keys.push(key)
      keys.push(...collectTreeKeys(node.children || []))
    }
    return keys
  }

  function buildPermissionLabelMap(nodes, parentLabel = '') {
    const labels = {}
    for (const node of nodes || []) {
      if (node.code?.startsWith('page:')) labels[node.code] = `页面:${node.label}`
      for (const operation of node.operations || []) {
        if (operation.code) labels[operation.code] = `${operation.resource_label || node.label}:${operation.label}`
      }
      Object.assign(labels, buildPermissionLabelMap(node.children || [], parentLabel))
    }
    return labels
  }

  function collectNodeCodes(node) {
    const codes = []
    if (node?.code) codes.push(node.code)
    for (const operation of node?.operations || []) {
      if (operation.code) codes.push(operation.code)
    }
    for (const child of node?.children || []) codes.push(...collectNodeCodes(child))
    return Array.from(new Set(codes))
  }

  function pageActionCodes(node) {
    return (node?.operations || []).map(operation => operation.code).filter(Boolean)
  }

  function addCodes(codes) {
    selectedPerms.value = Array.from(new Set([...selectedPerms.value, ...codes.filter(Boolean)]))
  }

  function removeCodes(codes) {
    const toRemove = new Set(codes.filter(Boolean))
    selectedPerms.value = selectedPerms.value.filter(code => !toRemove.has(code))
  }

  function ensurePageChain(node) {
    addCodes([...(node?.parent_codes || []), node?.code])
  }

  function isPageDisplayChecked(node) {
    return !!node?.code && selectedPerms.value.includes(node.code)
  }

  function togglePageDisplay(node, event) {
    wildcardSelected.value = false
    const checked = event?.target?.checked ?? !isPageDisplayChecked(node)
    if (checked) {
      ensurePageChain(node)
      return
    }
    removeCodes([node.code, ...pageActionCodes(node), ...collectTreeCodes(node.children || [])])
  }

  function isActionChecked(operation) {
    return !!operation?.code && selectedPerms.value.includes(operation.code)
  }

  function toggleAction(node, operation, event) {
    wildcardSelected.value = false
    const checked = event?.target?.checked ?? !isActionChecked(operation)
    if (checked) {
      ensurePageChain(node)
      addCodes([operation.code])
      return
    }
    removeCodes([operation.code])
  }

  function isPermissionExpanded(node) {
    const key = node.key || node.code || node.label
    return permissionExpanded.value.includes(key)
  }

  function togglePermissionExpand(node) {
    const key = node.key || node.code || node.label
    if (!key) return
    permissionExpanded.value = permissionExpanded.value.includes(key)
      ? permissionExpanded.value.filter(item => item !== key)
      : [...permissionExpanded.value, key]
  }

  function expandPermissionTree() {
    permissionExpanded.value = collectTreeKeys(permissionTree.value)
  }

  function collapsePermissionTree() {
    permissionExpanded.value = []
  }

  function isNodeChecked(node) {
    const codes = collectNodeCodes(node)
    return codes.length > 0 && codes.every(code => selectedPerms.value.includes(code))
  }

  function isNodePartial(node) {
    const codes = collectNodeCodes(node)
    const checked = codes.filter(code => selectedPerms.value.includes(code)).length
    return checked > 0 && checked < codes.length
  }

  function togglePermissionNode(node, event) {
    wildcardSelected.value = false
    const checked = event?.target?.checked ?? !isNodeChecked(node)
    const codes = collectNodeCodes(node)
    const next = new Set(selectedPerms.value)
    for (const code of codes) {
      if (checked) next.add(code)
      else next.delete(code)
    }
    selectedPerms.value = Array.from(next)
  }

  function selectAllPermissions() {
    wildcardSelected.value = false
    selectedPerms.value = [...permissionCodes.value]
  }

  function clearPermissions() {
    wildcardSelected.value = false
    selectedPerms.value = []
  }

  function toggleWildcardPermission() {
    selectedPerms.value = wildcardSelected.value ? [...permissionCodes.value] : selectedPerms.value
  }

  function selectNodePermissions(node) {
    wildcardSelected.value = false
    addCodes(collectNodeCodes(node))
  }

  function clearNodePermissions(node) {
    wildcardSelected.value = false
    removeCodes(collectNodeCodes(node))
  }

  function selectPagePreset(node, preset) {
    wildcardSelected.value = false
    if (preset === 'clear') {
      clearNodePermissions(node)
      return
    }
    ensurePageChain(node)
    const actions = node.operations || []
    if (preset === 'display') {
      removeCodes(pageActionCodes(node))
      return
    }
    const selectedActions = actions.filter(operation => {
      if (preset === 'view') return operation.action === 'view'
      if (preset === 'maintain') return ['view', 'create', 'edit', 'manage', 'report', 'export', 'admin'].includes(operation.action)
      if (preset === 'all') return true
      return false
    })
    addCodes(selectedActions.map(operation => operation.code))
  }

  function operationMatchesSearch(operation, keyword) {
    const text = `${operation.label || ''} ${operation.code || ''} ${operation.resource_label || ''}`.toLowerCase()
    return text.includes(keyword)
  }

  function nodeMatchesSearch(node, keyword) {
    const text = `${node.label || ''} ${node.code || ''} ${node.key || ''}`.toLowerCase()
    return text.includes(keyword)
  }

  function filterPermissionNode(node, keyword) {
    if (!keyword) return node
    const nodeMatched = nodeMatchesSearch(node, keyword)
    const operations = nodeMatched
      ? (node.operations || [])
      : (node.operations || []).filter(operation => operationMatchesSearch(operation, keyword))
    const children = nodeMatched
      ? (node.children || [])
      : (node.children || []).map(child => filterPermissionNode(child, keyword)).filter(Boolean)
    if (nodeMatched || operations.length || children.length) return { ...node, operations, children }
    return null
  }

  const filteredPermissionTree = computed(() => {
    const keyword = permissionSearch.value.trim().toLowerCase()
    return permissionTree.value.map(node => filterPermissionNode(node, keyword)).filter(Boolean)
  })

  const selectedPermCount = computed(() => wildcardSelected.value ? permissionCodes.value.length : selectedPerms.value.length)

  onMounted(() => { loadRoles(); loadGroups(); loadPermissions() })

  return {
    roles, groups, roleLoading, showRoleModal, roleModalEdit, roleForm, allPermissions, selectedPerms,
    permissionTree, filteredPermissionTree, permissionCodes, permissionSearch, permissionExpanded,
    wildcardSelected, selectedPermCount, permActionLabels, roleSearch, roleAddGroup, filteredRoles,
    loadRoles, loadGroups, loadPermissions, getGroupName, groupMap, formatPerms,
    openAddRole, openEditRole, saveRole, deleteRole,
    collectNodeCodes, isPermissionExpanded, togglePermissionExpand, expandPermissionTree,
    collapsePermissionTree, isNodeChecked, isNodePartial, togglePermissionNode,
    selectAllPermissions, clearPermissions, toggleWildcardPermission,
    isPageDisplayChecked, togglePageDisplay, isActionChecked, toggleAction,
    selectNodePermissions, clearNodePermissions, selectPagePreset,
  }
}
