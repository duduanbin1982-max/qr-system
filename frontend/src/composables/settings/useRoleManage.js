// useRoleManage.js
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useRoleManage() {
  const roles = ref([])
  const groups = ref([])
  const roleLoading = ref(false)
  const showRoleModal = ref(false)
  const roleModalEdit = ref(false)
  const roleForm = reactive({ name:'', code:'', description:'', group_id:null, parent_id:null, level:1, permissions:'', status:'active' })
  const allPermissions = ref([])
  const selectedPerms = ref([])
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
    try { const d = await api.get('/api/permissions'); allPermissions.value = d.permissions||[] }
    catch(e) { allPermissions.value = [] }
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
    try { const p = JSON.parse(permsStr||'[]'); return Array.isArray(p) ? p : [permsStr] }
    catch { return permsStr ? [permsStr] : [] }
  }
  function openAddRole() {
    roleModalEdit.value = false
    Object.assign(roleForm, { name:'', code:'', description:'', group_id:roleAddGroup.value, parent_id:null, level:1, permissions:'[]', status:'active' })
    selectedPerms.value = []
    showRoleModal.value = true
  }
  function expandStarPerms(perms) {
    if (!Array.isArray(perms)) return perms
    if (perms.includes('*')) {
      const all = []
      for (const p of allPermissions.value) {
        for (const act of (p.actions || [])) {
          all.push(p.code + ':' + act)
        }
      }
      return all
    }
    return perms
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
    roleForm.permissions = JSON.stringify(selectedPerms.value)
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

  onMounted(() => { loadRoles(); loadGroups(); loadPermissions() })

  return {
    roles, groups, roleLoading, showRoleModal, roleModalEdit, roleForm, allPermissions, selectedPerms,
    permActionLabels, roleSearch, roleAddGroup, filteredRoles,
    loadRoles, loadGroups, loadPermissions, getGroupName, groupMap, formatPerms,
    openAddRole, openEditRole, saveRole, deleteRole,
  }
}