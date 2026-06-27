import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

function isNonWorkerUser(user) {
  const roleCode = (user?.role_code || user?.role || '').toLowerCase()
  if (roleCode && roleCode !== 'worker') return true
  if (user?.is_admin_user) return true
  const roles = Array.isArray(user?.roles) ? user.roles : []
  return roles.some(role => (role?.code || '').toLowerCase() !== 'worker')
}

export function useAdminUsers() {
  const allUsers = ref([])
  const allRoles = ref([])
  const adminSearch = ref('')
  const adminLoading = ref(false)
  const selectedAdmins = ref([])
  const showAdminModal = ref(false)
  const adminModalEdit = ref(false)
  const adminForm = reactive({
    username: '',
    name: '',
    nickname: '',
    password: '',
    role: 'admin',
    role_id: null,
    email: '',
    phone: '',
    employee_no: '',
    status: 'active',
    group_name: '',
  })
  const roleGroups = ref([])
  const userRoleIds = ref([])

  const filteredAdminList = computed(() => {
    const kw = adminSearch.value.trim().toLowerCase()
    let list = allUsers.value.filter(isNonWorkerUser)
    if (kw) {
      list = list.filter(user =>
        (user.username || '').toLowerCase().includes(kw) ||
        (user.name || '').toLowerCase().includes(kw) ||
        (user.nickname || '').toLowerCase().includes(kw) ||
        (user.email || '').toLowerCase().includes(kw) ||
        (user.phone || '').toLowerCase().includes(kw) ||
        (user.employee_no || '').toLowerCase().includes(kw)
      )
    }
    return list
  })

  const isAllSelected = computed(() => {
    const ids = filteredAdminList.value.filter(user => !user.is_admin_user).map(user => user.id)
    return ids.length > 0 && ids.every(id => selectedAdmins.value.includes(id))
  })

  async function loadAllUsers() {
    adminLoading.value = true
    try {
      const data = await api.listUsers({ role_not: 'worker', limit: 500 })
      allUsers.value = data.users || []
    } catch (error) {
      showToast(error.message, 'error')
    } finally {
      adminLoading.value = false
    }
  }

  async function loadRoleGroups() {
    try {
      const data = await api.get('/api/role-groups')
      roleGroups.value = data.role_groups || []
    } catch (error) {
      console.warn('加载角色组失败', error.message || error)
    }
  }

  async function loadAllRoles() {
    try {
      const data = await api.get('/api/roles')
      allRoles.value = data.roles || []
    } catch (error) {
      allRoles.value = []
    }
  }

  function toggleSelectAllAdmins() {
    if (!isAllSelected.value) {
      selectedAdmins.value = filteredAdminList.value.filter(user => !user.is_admin_user).map(user => user.id)
    } else {
      selectedAdmins.value = []
    }
  }

  function openAddAdmin() {
    adminModalEdit.value = false
    Object.assign(adminForm, {
      username: '',
      name: '',
      nickname: '',
      password: '',
      role: 'admin',
      role_id: null,
      email: '',
      phone: '',
      employee_no: '',
      status: 'active',
      group_name: '',
    })
    delete adminForm._id
    userRoleIds.value = []
    showAdminModal.value = true
  }

  function openEditAdmin(user) {
    adminModalEdit.value = true
    Object.assign(adminForm, {
      username: user.username || '',
      name: user.name || '',
      nickname: user.nickname || '',
      password: '',
      role: user.role_code || user.role || 'admin',
      role_id: user.role_id || null,
      email: user.email || '',
      phone: user.phone || '',
      employee_no: user.employee_no || '',
      status: user.status || 'active',
      group_name: user.group_name || '',
    })
    adminForm._id = user.id
    loadUserRoles(user.id)
    showAdminModal.value = true
  }

  async function loadUserRoles(uid) {
    try {
      const data = await api.get('/api/users/' + uid + '/roles')
      userRoleIds.value = (data.roles || []).map(role => role.id)
    } catch (error) {
      userRoleIds.value = []
    }
  }

  function toggleUserRole(roleId) {
    const index = userRoleIds.value.indexOf(roleId)
    if (index >= 0) userRoleIds.value.splice(index, 1)
    else userRoleIds.value.push(roleId)
  }

  async function saveUserRoles(uid) {
    if (!uid) {
      showToast('请先保存用户', 'warn')
      return
    }
    try {
      await api.put('/api/users/' + uid + '/roles', { role_ids: [...userRoleIds.value] })
      showToast('角色保存成功')
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  async function saveAdmin() {
    if (!adminForm.username) {
      showToast('用户名不能为空', 'error')
      return
    }
    try {
      const body = {
        username: adminForm.username,
        name: adminForm.name,
        nickname: adminForm.nickname,
        role: adminForm.role || 'admin',
        email: adminForm.email,
        phone: adminForm.phone,
        employee_no: adminForm.employee_no,
        status: adminForm.status,
        group_name: adminForm.group_name,
      }
      if (adminForm.password) body.password = adminForm.password
      if (adminForm.role_id) body.role_id = adminForm.role_id

      let userId = adminForm._id
      if (adminModalEdit.value) {
        await api.updateUser(userId, body)
      } else {
        const result = await api.createUser(body)
        userId = result.id
      }

      if (adminModalEdit.value && userId) {
        await saveUserRoles(userId)
      }

      showToast(adminModalEdit.value ? '更新成功' : '创建成功')
      showAdminModal.value = false
      loadAllUsers()
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  async function deleteAdminUser(uid) {
    if (!confirm('确定删除该管理员？')) return
    try {
      await api.deleteUser(uid)
      showToast('删除成功')
      loadAllUsers()
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  async function restoreAdminUser(uid) {
    if (!confirm('确定恢复该管理员？')) return
    try {
      await api.restoreUser(uid)
      showToast('恢复成功')
      loadAllUsers()
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  async function permanentDeleteAdminUser(uid) {
    if (!confirm('彻底删除将无法恢复，确定继续？')) return
    try {
      await api.permanentDeleteUser(uid)
      showToast('已彻底删除')
      loadAllUsers()
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  async function batchDeleteAdmins() {
    if (selectedAdmins.value.length === 0) {
      showToast('请选择要删除的管理员', 'warn')
      return
    }
    if (!confirm('确定删除选中的 ' + selectedAdmins.value.length + ' 个管理员？')) return
    try {
      await api.post('/api/users/batch-delete', { ids: [...selectedAdmins.value] })
      showToast('已删除 ' + selectedAdmins.value.length + ' 个管理员')
      selectedAdmins.value = []
      loadAllUsers()
    } catch (error) {
      showToast(error.message, 'error')
    }
  }

  onMounted(() => {
    loadAllUsers()
    loadRoleGroups()
    loadAllRoles()
  })

  return {
    allUsers,
    allRoles,
    adminSearch,
    adminLoading,
    selectedAdmins,
    showAdminModal,
    adminModalEdit,
    adminForm,
    roleGroups,
    userRoleIds,
    filteredAdminList,
    isAllSelected,
    loadAllUsers,
    toggleSelectAllAdmins,
    openAddAdmin,
    openEditAdmin,
    saveAdmin,
    deleteAdminUser,
    restoreAdminUser,
    permanentDeleteAdminUser,
    batchDeleteAdmins,
    loadUserRoles,
    toggleUserRole,
    saveUserRoles,
    loadAllRoles,
    loadRoleGroups,
  }
}
