// useAdminUsers.js
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useAdminUsers() {
  const allUsers = ref([])
  const allRoles = ref([])
  const adminSearch = ref('')
  const adminLoading = ref(false)
  const selectedAdmins = ref([])
  const showAdminModal = ref(false)
  const adminModalEdit = ref(false)
  const adminForm = reactive({ username:'', name:'', nickname:'', password:'', role:'admin', email:'', phone:'', employee_no:'', status:'active', group_name:'' })
  const roleGroups = ref([])
  const userRoleIds = ref([])

  const filteredAdminList = computed(() => {
    let list = allUsers.value
    const kw = adminSearch.value.trim().toLowerCase()
    if (kw) list = list.filter(u => (u.username||'').toLowerCase().includes(kw) || (u.name||'').toLowerCase().includes(kw) || (u.nickname||'').toLowerCase().includes(kw) || (u.email||'').toLowerCase().includes(kw) || (u.phone||'').toLowerCase().includes(kw) || (u.employee_no||'').toLowerCase().includes(kw))
    return list
  })

  const isAllSelected = computed(() => {
    const ids = filteredAdminList.value.map(u => u.id)
    return ids.length > 0 && ids.every(id => selectedAdmins.value.includes(id))
  })

  async function loadAllUsers() {
    adminLoading.value = true
    try { const d = await api.get('/api/users?not_role=worker'); allUsers.value = d.users||[] }
    catch(e) { showToast(e.message,'error') }
    finally { adminLoading.value = false }
  }
  async function loadRoleGroups() {
    try { const d = await api.get('/api/role-groups'); roleGroups.value = d.role_groups||[] }
    catch(e) { console.warn('加载角色组失败:', e.message || e) }
  }
  async function loadAllRoles() {
    try { const d = await api.get('/api/roles'); allRoles.value = d.roles||[] }
    catch(e) { allRoles.value = [] }
  }
  function toggleSelectAllAdmins() {
    if (!isAllSelected.value) {
      selectedAdmins.value = filteredAdminList.value.map(u => u.id)
    } else {
      selectedAdmins.value = []
    }
  }
  function openAddAdmin() {
    adminModalEdit.value = false
    Object.assign(adminForm, { username:'', name:'', nickname:'', password:'', role:'admin', email:'', phone:'', employee_no:'', status:'active', group_name:'' })
    userRoleIds.value = []
    showAdminModal.value = true
  }
  function openEditAdmin(user) {
    adminModalEdit.value = true
    Object.assign(adminForm, { username:user.username, name:user.name||'', nickname:user.nickname||'', password:'', email:user.email||'', phone:user.phone||'', employee_no:user.employee_no||'', status:user.status||'active', group_name:user.group_name||'' })
    adminForm._id = user.id
    loadUserRoles(user.id)
    showAdminModal.value = true
  }
  async function loadUserRoles(uid) {
    try { const d = await api.get('/api/users/' + uid + '/roles'); userRoleIds.value = (d.roles||[]).map(r => r.id) }
    catch(e) { userRoleIds.value = [] }
  }
  function toggleUserRole(rid) {
    const idx = userRoleIds.value.indexOf(rid)
    if (idx >= 0) userRoleIds.value.splice(idx, 1)
    else userRoleIds.value.push(rid)
  }
  async function saveUserRoles(uid) {
    if (!uid) { showToast('请先保存用户','warn'); return }
    try { await api.put('/api/users/' + uid + '/roles', { role_ids: [...userRoleIds.value] }); showToast('角色保存成功') }
    catch(e) { showToast(e.message,'error') }
  }
  async function saveAdmin() {
    if (!adminForm.username) { showToast('用户名不能为空','error'); return }
    try {
      const body = { username:adminForm.username, name:adminForm.name, nickname:adminForm.nickname, role:adminForm.role || 'admin', email:adminForm.email, phone:adminForm.phone, employee_no:adminForm.employee_no, status:adminForm.status, group_name:adminForm.group_name }
      if (adminForm.password) body.password = adminForm.password

      let userId = adminForm._id
      if (adminModalEdit.value) {
        await api.updateUser(userId, body)
      } else {
        const res = await api.createUser(body)
        userId = res.id
      }

      if (userRoleIds.value.length > 0 && userId) {
        try { await saveUserRoles(userId) }
        catch(e) { showToast('用户已创建，但角色分配失败: ' + e.message, 'warn') }
      }

      showToast(adminModalEdit.value?'更新成功':'创建成功')
      showAdminModal.value = false
      loadAllUsers()
    } catch(e) { showToast(e.message,'error') }
  }
  async function deleteAdminUser(uid) {
    if (!confirm('确定删除该管理员？')) return
    try { await api.deleteUser(uid); showToast('删除成功'); loadAllUsers() }
    catch(e) { showToast(e.message,'error') }
  }
  async function restoreAdminUser(uid) {
    if (!confirm('确定恢复该管理员？')) return
    try { await api.restoreUser(uid); showToast('恢复成功'); loadAllUsers() }
    catch(e) { showToast(e.message,'error') }
  }
  async function permanentDeleteAdminUser(uid) {
    if (!confirm('彻底删除将无法恢复，确定继续？')) return
    try { await api.permanentDeleteUser(uid); showToast('已彻底删除'); loadAllUsers() }
    catch(e) { showToast(e.message,'error') }
  }
  async function batchDeleteAdmins() {
    if (selectedAdmins.value.length === 0) { showToast('请选择要删除的管理员','warn'); return }
    if (!confirm('确定删除选中的 ' + selectedAdmins.value.length + ' 个管理员？')) return
    try {
      await api.post('/api/users/batch-delete', { ids: [...selectedAdmins.value] })
      showToast('已删除 ' + selectedAdmins.value.length + ' 个管理员')
      selectedAdmins.value = []
      loadAllUsers()
    } catch(e) { showToast(e.message,'error') }
  }

  onMounted(() => { loadAllUsers(); loadRoleGroups(); loadAllRoles() })

  return {
    allUsers, allRoles, adminSearch, adminLoading, selectedAdmins,
    showAdminModal, adminModalEdit, adminForm, roleGroups, userRoleIds,
    filteredAdminList, isAllSelected,
    loadAllUsers, toggleSelectAllAdmins, openAddAdmin, openEditAdmin, saveAdmin,
    deleteAdminUser, restoreAdminUser, permanentDeleteAdminUser, batchDeleteAdmins, loadUserRoles, toggleUserRole, saveUserRoles,
    loadAllRoles, loadRoleGroups,
  }
}