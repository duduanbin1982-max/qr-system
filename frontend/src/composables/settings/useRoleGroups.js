// useRoleGroups.js
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useRoleGroups() {
  const groups = ref([])
  const roles = ref([])
  const groupLoading = ref(false)
  const showGroupModal = ref(false)
  const groupModalEdit = ref(false)
  const groupForm = reactive({ name:'', description:'', parent_id:null, status:'active', permissions:'' })
  const expandedGroup = ref(null)

  const groupRoles = computed(() =>
    expandedGroup.value
      ? roles.value.filter(r => r.group_id === expandedGroup.value)
      : []
  )

  const roleCountByGroup = computed(() => {
    const map = {}
    for (const r of roles.value) { const gid = r.group_id||0; map[gid] = (map[gid]||0) + 1 }
    return map
  })

  const childrenCountByGroup = computed(() => {
    const map = {}
    for (const g of groups.value) {
      if (g.parent_id) map[g.parent_id] = (map[g.parent_id]||0) + 1
    }
    return map
  })

  const canDeleteGroup = (gid) => {
    return (roleCountByGroup.value[gid]||0) === 0 && (childrenCountByGroup.value[gid]||0) === 0
  }

  async function loadGroups() {
    groupLoading.value = true
    try { const d = await api.get('/api/role-groups'); groups.value = d.role_groups||[] }
    catch(e) { showToast(e.message,'error') }
    finally { groupLoading.value = false }
  }

  async function loadRoles() {
    try { const d = await api.get('/api/roles'); roles.value = d.roles||[] }
    catch(e) { roles.value = [] }
  }

  function toggleGroup(gid) { expandedGroup.value = expandedGroup.value === gid ? null : gid }

  function openAddGroup() {
    groupModalEdit.value = false
    Object.assign(groupForm, { name:'', description:'', parent_id:null, status:'active', permissions:'' })
    showGroupModal.value = true
  }

  function openEditGroup(group) {
    groupModalEdit.value = true
    Object.assign(groupForm, { name:group.name, description:group.description||'', parent_id:group.parent_id, status:group.status||'active', permissions:group.permissions||'' })
    groupForm._id = group.id
    showGroupModal.value = true
  }

  async function saveGroup() {
    if (!groupForm.name) { showToast('角色组名称不能为空','error'); return }
    try {
      const body = { name:groupForm.name, description:groupForm.description, parent_id:groupForm.parent_id, status:groupForm.status }
      if (groupModalEdit.value) await api.updateRoleGroup(groupForm._id, body)
      else await api.createRoleGroup(body)
      showToast(groupModalEdit.value?'更新成功':'创建成功')
      showGroupModal.value = false
      loadGroups()
    } catch(e) { showToast(e.message,'error') }
  }

  async function deleteGroup(gid) {
    if (!confirm('确定删除该角色组？')) return
    try { await api.deleteRoleGroup(gid); showToast('删除成功'); loadGroups() }
    catch(e) { showToast(e.message,'error') }
  }

  onMounted(() => { loadGroups(); loadRoles(); })

  return {
    groups, roles, groupLoading, showGroupModal, groupModalEdit, groupForm,
    expandedGroup, groupRoles, roleCountByGroup,
    loadGroups, loadRoles, toggleGroup, openAddGroup, openEditGroup, saveGroup, deleteGroup, canDeleteGroup, childrenCountByGroup,

  }
}