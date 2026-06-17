// Admin Users Composable — extracted from useSettings.js
// Uses shared `allUsers`, `allRoles` from parent composable
import { ref, reactive, computed } from '''vue'''

export function useAdmin(allUsers, allRoles) {
  const adminSearch = ref(''''''')
  const adminLoading = ref(false)
  const selectedAdmins = ref([])
  const adminSelectAll = ref(false)
  const showAdminModal = ref(false)
  const adminModalEdit = ref(false)
  const adminForm = reactive({ username:'''''', name:'''''', nickname:'''''', password:'''''', role:'''admin''', email:'''''', phone:'''''', employee_no:'''''', group_name:'''超级管理组''', status:'''active''' })
  const userRoleIds = ref([])

  const filteredAdminList = computed(() => {
    let list = allUsers.value.filter(u => u.role === '''admin''')
    const kw = adminSearch.value.trim().toLowerCase()
    if (kw) list = list.filter(u =>
      (u.username||'''''').toLowerCase().includes(kw) ||
      (u.name||'''''').toLowerCase().includes(kw) ||
      (u.nickname||'''''').toLowerCase().includes(kw)
    )
    return list
  })

  function toggleSelectAllAdmins() {
    if (adminSelectAll.value) selectedAdmins.value = filteredAdminList.value.map(u=>u.id)
    else selectedAdmins.value = []
  }

  function openAddAdmin() {
    Object.assign(adminForm, { username:'''''', name:'''''', nickname:'''''', password:'''''', role:'''admin''', email:'''''', phone:'''''', employee_no:'''''', group_name:'''超级管理组''', status:'''active''' })
    userRoleIds.value = []
    adminModalEdit.value = false; showAdminModal.value = true
  }

  function openEditAdmin(u) {
    Object.assign(adminForm, { _id:u.id, username:u.username, name:u.name||'''''', nickname:u.nickname||'''''', role:u.role||'''admin''', email:u.email||'''''', phone:u.phone||'''''', employee_no:u.employee_no||'''''', group_name:u.group_name||'''超级管理组''', status:u.status||'''active''', password:'''''' })
    adminModalEdit.value = true; showAdminModal.value = true
  }

  return {
    adminSearch, adminLoading, selectedAdmins, adminSelectAll,
    showAdminModal, adminModalEdit, adminForm, userRoleIds, filteredAdminList,
    toggleSelectAllAdmins, openAddAdmin, openEditAdmin
  }
}
