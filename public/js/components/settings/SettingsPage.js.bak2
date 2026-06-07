// SettingsPage Component — 系统设置（6个子模块）
import { ref, reactive, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js'
import { showToast } from '../../store.js'

export default {
  template: '#settings-page-template',
  setup() {
    // ===== Tab State =====
    const activeTab = ref('company-info')
    const tabs = [
      { key:'company-info', label:'🏢 公司资料' },
      { key:'admin-users', label:'👥 管理员管理' },
      { key:'audit-logs', label:'📋 操作日志' },
      { key:'process-config', label:'⚙️ 工艺管理' },
      { key:'role-groups', label:'👔 角色组' },
      { key:'role-manage', label:'👥 角色管理' },
      { key:'positions', label:'💼 岗位管理' },
    ]

    // ===== 公司资料 =====
    const settings = ref({})
    const edits = ref({})
    const loading = ref(true)
    const saving = ref(false)
    const deletedKeys = ref(new Set())
    const templates = {
      company_name:'公司名称', contact:'联系人', phone:'联系电话',
      address:'公司地址', description:'公司简介',
      default_password:'默认密码',
      approval_enabled:'是否启用审批 (1=是 0=否)',
      auto_order_no:'自动生成订单号前缀', page_size:'列表每页条数',
    }

    async function loadSettings() {
      loading.value = true
      try { const d = await api.getSettings(); settings.value = d.settings||{}; edits.value = {...settings.value}; deletedKeys.value = new Set() }
      catch(e) { showToast(e.message,'error') }
      finally { loading.value = false }
    }
    async function saveSettings() {
      saving.value = true
      try {
        const payload = { ...edits.value }
        if (deletedKeys.value.size > 0) payload._deleted_keys = [...deletedKeys.value]
        await api.saveSettings(payload)
        showToast('保存成功')
        settings.value = {...edits.value}
        deletedKeys.value = new Set()
      }
      catch(e) { showToast(e.message,'error') }
      finally { saving.value = false }
    }
    function addSetting() {
      const key = (prompt('设置项名称（英文）：') || '').trim()
      if (!key) { showToast('设置项名称不能为空', 'warn'); return }
      if (key in edits.value) { showToast(`设置项 "${key}" 已存在`, 'warn'); return }
      edits.value = {...edits.value, [key]: ''}
    }
    function removeSetting(key) {
      if(!confirm('确定删除 ' + labelOf(key) + ' 吗？')) return
      const newEdits = {...edits.value}
      delete newEdits[key]
      edits.value = newEdits
      deletedKeys.value = new Set([...deletedKeys.value, key])
    }
    function labelOf(key) { return templates[key] || `未知设置 (${key})` }

    // ===== 管理员管理 =====
    const adminUsers = ref([])
    const allUsers = ref([])
    const adminSearch = ref('')
    const adminLoading = ref(false)
    const selectedAdmins = ref([])
    const adminSelectAll = ref(false)
    const showAdminModal = ref(false)
    const adminModalEdit = ref(false)
    const adminForm = reactive({ username:'', name:'', nickname:'', password:'', role:'admin', email:'', phone:'', employee_no:'', group_name:'超级管理组' })
    const roleGroups = ref([])

    const filteredAdminList = computed(() => {
      let list = allUsers.value.filter(u => u.role === 'admin')
      const kw = adminSearch.value.trim().toLowerCase()
      if (kw) list = list.filter(u => (u.username||'').toLowerCase().includes(kw) || (u.name||'').toLowerCase().includes(kw) || (u.nickname||'').toLowerCase().includes(kw))
      return list
    })

    async function loadAllUsers() {
      adminLoading.value = true
      try { const d = await api.get('/api/users'); allUsers.value = d.users||[] }
      catch(e) { showToast(e.message,'error') }
      finally { adminLoading.value = false }
    }
    async function loadRoleGroups() {
      try { const d = await api.get('/api/role-groups'); roleGroups.value = d.role_groups||[] }
      catch(e) { showToast('加载角色组失败', 'warn') }
    }
    function toggleSelectAllAdmins() {
      if (adminSelectAll.value) selectedAdmins.value = filteredAdminList.value.map(u=>u.id)
      else selectedAdmins.value = []
    }
    function openAddAdmin() {
      Object.assign(adminForm, { username:'', name:'', nickname:'', password:'', role:'admin', email:'', phone:'', employee_no:'', group_name:'超级管理组' })
      adminModalEdit.value = false; showAdminModal.value = true
    }
    function openEditAdmin(u) {
      Object.assign(adminForm, { _id:u.id, username:u.username, name:u.name||'', nickname:u.nickname||'', role:u.role||'admin', email:u.email||'', phone:u.phone||'', employee_no:u.employee_no||'', group_name:u.group_name||'超级管理组', password:'' })
      adminModalEdit.value = true; showAdminModal.value = true
    }
    async function saveAdmin() {
      if (!adminForm.username || !adminForm.name) { showToast('用户名和姓名为必填','error'); return }
      const body = { username:adminForm.username, name:adminForm.name, nickname:adminForm.nickname, role:adminForm.role, email:adminForm.email, phone:adminForm.phone, employee_no:adminForm.employee_no, group_name:adminForm.group_name }
      if (adminForm.password) body.password = adminForm.password
      try {
        if (adminModalEdit.value) await api.updateUser(adminForm._id, body)
        else await api.createUser(body)
        showToast(adminModalEdit.value?'更新成功':'创建成功')
        showAdminModal.value = false; loadAllUsers()
      } catch(e) { showToast(e.message,'error') }
    }
    async function deleteAdminUser(uid) {
      const u = allUsers.value.find(x => x.id === uid)
      const name = u ? (u.name || u.username) : uid
      if (!confirm(`确定删除管理员「${name}」吗？`)) return
      try { await api.deleteUser(uid); showToast('删除成功'); loadAllUsers() }
      catch(e) { showToast(e.message,'error') }
    }
    async function batchDeleteAdmins() {
      if (!selectedAdmins.value.length) return
      // 过滤掉内置 admin 用户
      const safe = selectedAdmins.value.filter(id => {
        const u = allUsers.value.find(x => x.id === id)
        if (u && u.username === 'admin') { showToast('不能删除系统内置管理员 admin','warn'); return false }
        return true
      })
      if (!safe.length) return
      if (!confirm('确定删除选中的 '+safe.length+' 个管理员？')) return
      let success = 0, failed = 0
      for (const uid of safe) {
        try { await api.deleteUser(uid); success++ }
        catch(e) { showToast('删除失败: '+(e.message||uid), 'error'); failed++ }
      }
      const msg = failed ? `删除完成: ${success} 成功, ${failed} 失败` : `已删除 ${success} 个管理员`
      showToast(msg, failed ? 'warn' : undefined)
      selectedAdmins.value = []; adminSelectAll.value = false; loadAllUsers()
    }

    // ===== 操作日志 =====
    const logs = ref([])
    const logsTotal = ref(0)
    const logsPage = ref(1)
    const logsLoading = ref(false)
    const logsLimit = 50
    const logFilterAction = ref('')
    const logFilterKeyword = ref('')
    const logFilterDateFrom = ref('')
    const logFilterDateTo = ref('')
    const expandedLogId = ref(null)

    async function loadLogs() {
      logsLoading.value = true
      try {
        const params = { page: logsPage.value, limit: logsLimit }
        if (logFilterAction.value) params.action = logFilterAction.value
        if (logFilterKeyword.value) params.keyword = logFilterKeyword.value
        if (logFilterDateFrom.value) params.date_from = logFilterDateFrom.value
        if (logFilterDateTo.value) params.date_to = logFilterDateTo.value
        const d = await api.listLogs(params)
        logs.value = d.logs||[]; logsTotal.value = d.total||0
      } catch(e) { showToast(e.message,'error') }
      finally { logsLoading.value = false }
    }
    function logsPrevPage() { if (logsPage.value>1) { logsPage.value--; loadLogs() } }
    function logsNextPage() { if (logsPage.value*logsLimit<logsTotal.value) { logsPage.value++; loadLogs() } }

    // ===== 工艺管理 =====
    const processes = ref([])
    const processLoading = ref(false)
    const processConfig = reactive({
      process_order_mode: 'sequential',
      delivery_warning_days: 3,
      limit_by_prev_process: 0,
      limit_by_order_qty: 0,
      approval_enabled: 0,
      auto_order_no: '',
      page_size: 20,
    })
    const processConfigLoading = ref(false)
    const processConfigSaving = ref(false)
    async function loadProcesses() {
      processLoading.value = true
      try { const d = await api.get('/api/processes'); processes.value = d.processes||[] }
      catch(e) { showToast(e.message,'error') }
      finally { processLoading.value = false }
    }
    async function loadProcessConfig() {
      processConfigLoading.value = true
      try {
        const d = await api.getSettings()
        const s = d.settings || {}
        if (s.process_order_mode) processConfig.process_order_mode = s.process_order_mode
        if (s.delivery_warning_days) processConfig.delivery_warning_days = parseInt(s.delivery_warning_days) || 3
        if (s.limit_by_prev_process !== undefined) processConfig.limit_by_prev_process = parseInt(s.limit_by_prev_process) || 0
        if (s.limit_by_order_qty !== undefined) processConfig.limit_by_order_qty = parseInt(s.limit_by_order_qty) || 0
        if (s.approval_enabled !== undefined) processConfig.approval_enabled = parseInt(s.approval_enabled) || 0
        processConfig.auto_order_no = s.auto_order_no || ''
        if (s.page_size) processConfig.page_size = parseInt(s.page_size) || 20
      } catch(e) { showToast(e.message, 'error') }
      finally { processConfigLoading.value = false }
    }
    async function saveProcessConfig() {
      processConfigSaving.value = true
      try {
        await api.saveSettings({ ...processConfig })
        showToast('工艺配置保存成功')
      } catch(e) { showToast(e.message, 'error') }
      finally { processConfigSaving.value = false }
    }

    // ===== 角色组 =====
    const groups = ref([])
    const roles = ref([])
    const groupLoading = ref(false)
    const roleLoading = ref(false)
    const showGroupModal = ref(false)
    const groupModalEdit = ref(false)
    const groupForm = reactive({ name:'', description:'', parent_id:null, status:'active' })
    const showRoleModal = ref(false)
    const roleModalEdit = ref(false)
    const roleForm = reactive({ name:'', code:'', description:'', group_id:null, parent_id:null, level:1, permissions:'', status:'active' })
    const expandedGroup = ref(null)
    const groupRoles = ref([])

    // 权限系统
    const allPermissions = ref([])
    const selectedPerms = ref([])
    const permActionLabels = [
      { key: 'view', label: '查看' },
      { key: 'create', label: '新增' },
      { key: 'edit', label: '编辑' },
      { key: 'delete', label: '删除' },
      { key: 'manage', label: '管理' },
    ]

    async function loadPermissions() {
      try { const d = await api.get('/api/permissions'); allPermissions.value = d.permissions||[] }
      catch(e) { /* non-critical */ }
    }

    async function loadGroups() {
      groupLoading.value = true
      try { const d = await api.listRoleGroups(); groups.value = d.role_groups||[] }
      catch(e) { showToast(e.message,'error') }
      finally { groupLoading.value = false }
    }
    async function loadRoles() {
      roleLoading.value = true
      try { const d = await api.listRoles(); roles.value = d.roles||[] }
      catch(e) { showToast('加载角色列表失败', 'warn') }
      finally { roleLoading.value = false }
    }
    function toggleGroup(gid) {
      if (expandedGroup.value === gid) { expandedGroup.value = null; return }
      expandedGroup.value = gid
      groupRoles.value = roles.value.filter(r => r.group_id === gid)
    }
    function openAddGroup() {
      Object.assign(groupForm, { name:'', description:'', parent_id:null, status:'active' })
      groupModalEdit.value = false; showGroupModal.value = true
    }
    function openEditGroup(g) {
      Object.assign(groupForm, { _id:g.id, name:g.name, description:g.description||'', parent_id:g.parent_id, status:g.status })
      groupModalEdit.value = true; showGroupModal.value = true
    }
    async function saveGroup() {
      if (!groupForm.name) { showToast('名称不能为空','error'); return }
      const body = { name:groupForm.name, description:groupForm.description, parent_id:groupForm.parent_id, status:groupForm.status }
      try {
        if (groupModalEdit.value) await api.updateRoleGroup(groupForm._id, body)
        else await api.createRoleGroup(body)
        showToast(groupModalEdit.value?'更新成功':'创建成功')
        showGroupModal.value = false; loadGroups()
      } catch(e) { showToast(e.message,'error') }
    }
    async function deleteGroup(gid) {
      // 前端先检查子级角色组（与后端保持一致）
      const children = groups.value.filter(g => g.parent_id === gid)
      if (children.length) {
        showToast(`该角色组有 ${children.length} 个下级角色组（${children.map(g=>g.name).join('、')}），无法删除`, 'warn')
        return
      }
      if (!confirm('确定删除该角色组？组内所有角色及角色分配将被级联删除')) return
      try { await api.deleteRoleGroup(gid); showToast('删除成功'); loadGroups(); loadRoles() }
      catch(e) { showToast(e.message,'error') }
    }
    function openAddRole(gid) {
      Object.assign(roleForm, { name:'', code:'', description:'', group_id:gid, parent_id:null, level:1, permissions:'', status:'active' })
      selectedPerms.value = []
      roleModalEdit.value = false; showRoleModal.value = true
    }
    function openEditRole(r) {
      Object.assign(roleForm, { _id:r.id, name:r.name, code:r.code, description:r.description||'', group_id:r.group_id, parent_id:r.parent_id, level:r.level||1, permissions:r.permissions||'', status:r.status })
      // 解析已有权限
      try { selectedPerms.value = JSON.parse(r.permissions || '[]') } catch(e) { selectedPerms.value = [] }
      roleModalEdit.value = true; showRoleModal.value = true
    }
    async function saveRole() {
      if (!roleForm.name || !roleForm.code) { showToast('名称和编码为必填','error'); return }
      const body = { name:roleForm.name, code:roleForm.code, description:roleForm.description, group_id:roleForm.group_id, parent_id:roleForm.parent_id, level:roleForm.level, permissions: JSON.stringify(selectedPerms.value), status:roleForm.status }
      try {
        if (roleModalEdit.value) await api.updateRole(roleForm._id, body)
        else await api.createRole(body)
        showToast(roleModalEdit.value?'更新成功':'创建成功')
        showRoleModal.value = false; loadRoles()
        // Refresh group view
        if (expandedGroup.value) {
          groupRoles.value = roles.value.filter(r => r.group_id === expandedGroup.value)
        }
      } catch(e) { showToast(e.message,'error') }
    }
    async function deleteRole(rid) {
      if (!confirm('确定删除该角色？已分配此角色的用户将失去对应权限')) return
      try { await api.deleteRole(rid); showToast('删除成功'); loadRoles()
        if (expandedGroup.value) groupRoles.value = roles.value.filter(r => r.group_id === expandedGroup.value)
      } catch(e) { showToast(e.message,'error') }
    }

    // 角色管理 — 搜索/过滤/辅助
    const roleSearch = ref('')
    const roleAddGroup = ref(1)  // 默认系统管理组
    // 按组统计角色数量（避免模板中 O(n×m) 计算）
    const roleCountByGroup = computed(() => {
      const map = {}
      for (const r of roles.value) {
        const gid = r.group_id
        map[gid] = (map[gid] || 0) + 1
      }
      return map
    })
    // 预计算角色权限（避免模板中每行重复 JSON.parse）
    const rolePerms = computed(() => {
      const map = {}
      for (const r of roles.value) {
        try {
          const arr = typeof r.permissions === 'string' ? JSON.parse(r.permissions || '[]') : (r.permissions || [])
          map[r.id] = arr.includes('*') ? ['全部权限'] : arr
        } catch(e) { map[r.id] = [] }
      }
      return map
    })

    const filteredRoles = computed(() => {
      let list = roles.value
      const kw = roleSearch.value.trim().toLowerCase()
      if (kw) list = list.filter(r =>
        (r.name||'').toLowerCase().includes(kw) ||
        (r.code||'').toLowerCase().includes(kw)
      )
      return list
    })
    function getGroupName(gid) {
      const g = groups.value.find(g => g.id === gid)
      return g ? g.name : '未知'
    }
    function formatPerms(permissions) {
      if (!permissions) return []
      try {
        const arr = typeof permissions === 'string' ? JSON.parse(permissions) : permissions
        if (arr.includes('*')) return ['全部权限']
        return arr
      } catch(e) { return [] }
    }

    // ===== 岗位管理 =====
    const positions = ref([])
    const positionLoading = ref(false)
    const showPositionModal = ref(false)
    const positionModalEdit = ref(false)
    const positionForm = reactive({ name:'', description:'', process_ids:[], status:'active' })
    const allProcesses = ref([])

    async function loadPositions() {
      positionLoading.value = true
      try { const d = await api.listPositions(); positions.value = d.positions||[] }
      catch(e) { showToast(e.message,'error') }
      finally { positionLoading.value = false }
    }
    async function loadAllProcesses() {
      try { const d = await api.get('/api/processes'); allProcesses.value = d.processes||[] }
      catch(e) { showToast('加载工序列表失败', 'warn') }
    }
    function openAddPosition() {
      Object.assign(positionForm, { name:'', description:'', process_ids:[], status:'active' })
      positionModalEdit.value = false; showPositionModal.value = true
    }
    function openEditPosition(p) {
      Object.assign(positionForm, { _id:p.id, name:p.name, description:p.description||'', status:p.status||'active', process_ids:(p.processes||[]).map(pr=>pr.process_id) })
      positionModalEdit.value = true; showPositionModal.value = true
    }
    async function savePosition() {
      if (!positionForm.name) { showToast('岗位名称不能为空','error'); return }
      try {
        const body = { name:positionForm.name, description:positionForm.description, status:positionForm.status, process_ids:positionForm.process_ids }
        if (positionModalEdit.value) await api.updatePosition(positionForm._id, body)
        else await api.createPosition(body)
        showToast(positionModalEdit.value?'更新成功':'创建成功')
        showPositionModal.value = false; loadPositions()
      } catch(e) { showToast(e.message,'error') }
    }
    async function deletePosition(pid) {
      if (!confirm('确定删除该岗位？')) return
      try { await api.deletePosition(pid); showToast('删除成功'); loadPositions() }
      catch(e) { showToast(e.message,'error') }
    }
    function toggleProcessInPosition(pid) {
      const idx = positionForm.process_ids.indexOf(pid)
      if (idx >= 0) positionForm.process_ids.splice(idx, 1)
      else positionForm.process_ids.push(pid)
    }

    // ===== Init =====
    onMounted(() => {
      loadSettings()
      loadAllUsers()
      loadRoleGroups()
      loadGroups()
      loadRoles()
      loadPermissions()
      loadProcesses()
      loadProcessConfig()
      loadAllProcesses()
      loadPositions()
      loadLogs()
    })

    return {
      activeTab, tabs,
      settings, edits, loading, saving, templates, loadSettings, saveSettings, addSetting, removeSetting, labelOf,
      adminUsers, allUsers, adminSearch, adminLoading, selectedAdmins, adminSelectAll, showAdminModal, adminModalEdit, adminForm, roleGroups,
      filteredAdminList, loadAllUsers, toggleSelectAllAdmins, openAddAdmin, openEditAdmin, saveAdmin, deleteAdminUser, batchDeleteAdmins,
      logs, logsTotal, logsPage, logsLoading, logsLimit, logFilterAction, logFilterKeyword, logFilterDateFrom, logFilterDateTo, expandedLogId, loadLogs, logsPrevPage, logsNextPage,
      processes, processLoading, processConfig, processConfigLoading, processConfigSaving, loadProcesses, loadProcessConfig, saveProcessConfig,
      groups, roles, groupLoading, showGroupModal, groupModalEdit, groupForm, showRoleModal, roleModalEdit, roleForm, expandedGroup, groupRoles,
      loadGroups, loadRoles, toggleGroup, openAddGroup, openEditGroup, saveGroup, deleteGroup, openAddRole, openEditRole, saveRole, deleteRole,
      allPermissions, selectedPerms, permActionLabels, loadPermissions,
      roleSearch, roleLoading, roleCountByGroup, rolePerms, filteredRoles, getGroupName, formatPerms, roleAddGroup,
      positions, positionLoading, showPositionModal, positionModalEdit, positionForm, allProcesses,
      loadPositions, loadAllProcesses, openAddPosition, openEditPosition, savePosition, deletePosition, toggleProcessInPosition,
    }
  }
}
