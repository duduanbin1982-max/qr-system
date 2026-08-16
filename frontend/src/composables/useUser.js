import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export function useUser() {
  const users = ref([])
  const positions = ref([])
  const processes = ref([])
  const processDropdownOpen = ref(false)
  const dropdownStyle = ref({})
  const processSearch = ref('')
  const selectedProcessIds = ref([])
  const loading = ref(true)
  const saving = ref(false)
  const searchKeyword = ref('')
  const page = ref(1)
  const total = ref(0)
  const summary = ref({ total: 0, active: 0, inactive: 0, deleted: 0 })
  const pageSize = 20

  const showModal = ref(false)
  const modalEdit = ref(false)
  const modalId = ref(null)
  const form = ref({
    username: '', name: '', email: '',
    status: 'active',
    employee_no: '', marker: '', phone: '', process_ids: '', password: '',
    position_id: ''
  })

  const canCreate = computed(() => can('users:create'))
  const canEdit = computed(() => can('users:edit'))
  const canDelete = computed(() => can('users:delete'))
  const canAdmin = computed(() => can('users:admin'))

  const activeCount = computed(() => summary.value.active)
  const inactiveCount = computed(() => summary.value.inactive)
  const deletedCount = computed(() => summary.value.deleted)
  const totalStaff = computed(() => activeCount.value + inactiveCount.value)

  const positionMap = computed(() => {
    const map = {}
    for (const p of positions.value) { map[p.id] = p.name }
    return map
  })

  function getPositionName(position_id) {
    if (!position_id) return '未分配'
    return positionMap.value[position_id] || '未知'
  }

  function getWorkProcesses(user) {
    if (Array.isArray(user.work_processes) && user.work_processes.length) {
      return user.work_processes
    }
    if (Array.isArray(user.position_processes) || Array.isArray(user.explicit_processes)) {
      const merged = []
      const seen = new Set()
      for (const process of [...(user.position_processes || []), ...(user.explicit_processes || [])]) {
        if (!process || seen.has(process.id)) continue
        seen.add(process.id)
        merged.push(process)
      }
      return merged
    }
    const ids = (user.process_ids || '').split(',').map(x => parseInt(x.trim())).filter(x => !isNaN(x))
    return ids.map(id => {
      const process = processes.value.find(p => p.id === id)
      return { id, name: process ? process.process_name : '#' + id, source: '员工' }
    })
  }

  function getWorkProcessTitle(user) {
    return getWorkProcesses(user).map(process => process.name).join('、')
  }

  async function load() {
      loading.value = true
      try {
        const [userData, posData, procData] = await Promise.all([
        api.domains.users.listUsers({ page: page.value, limit: pageSize, keyword: searchKeyword.value, role: 'worker' }),
          api.domains.positions.listPositions(),
          api.domains.processes.listProcesses()
        ])
      users.value = userData.users || []
      total.value = userData.total || 0
      summary.value = {
        total: Number(userData.summary?.total || 0),
        active: Number(userData.summary?.active || 0),
        inactive: Number(userData.summary?.inactive || 0),
        deleted: Number(userData.summary?.deleted || 0)
      }
      positions.value = posData.positions || []
      processes.value = procData.processes || []
    } catch(e) {
      showToast(e.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  function searchAndLoad() {
    page.value = 1
    load()
  }

  function prevPage() { if (page.value > 1) { page.value--; load() } }
  function nextPage() {
    if (page.value * pageSize < total.value) { page.value++; load() }
  }

  const filteredProcessList = computed(() => {
    if (!processSearch.value) return processes.value
    const kw = processSearch.value.toLowerCase()
    return processes.value.filter(p =>
      (p.process_name || '').toLowerCase().includes(kw) ||
      (p.category || '').toLowerCase().includes(kw)
    )
  })

  const selectedProcessNames = computed(() => {
    return selectedProcessIds.value.map(id => {
      const p = processes.value.find(pp => pp.id === id)
      return { id, name: p ? p.process_name : '#' + id }
    })
  })

  function toggleProcessDropdown(event) {
    if (processDropdownOpen.value) {
      processDropdownOpen.value = false
      return
    }
    const trigger = event.target.closest('.multi-select-trigger') || event.target
    const rect = trigger.getBoundingClientRect()
    dropdownStyle.value = {
      top: (rect.bottom + 4) + 'px',
      left: rect.left + 'px',
      width: Math.max(rect.width, 320) + 'px'
    }
    processDropdownOpen.value = true
  }

  function onProcessChange() {
    form.value.process_ids = selectedProcessIds.value.join(',')
  }

  function openAdd() {
    form.value = {
      username: '', name: '', email: '',
      role: 'worker',
      status: 'active',
      employee_no: '', marker: '', phone: '', process_ids: '', password: '',
      position_id: ''
    }
    modalEdit.value = false
    modalId.value = null
    processDropdownOpen.value = false
    processSearch.value = ''
    selectedProcessIds.value = []
    showModal.value = true
  }

  function openEdit(u) {
    form.value = {
      username: u.username || '',
      name: u.name || '',
      email: u.email || '',
      status: u.status || 'active',
      employee_no: u.employee_no || '',
      marker: u.marker || '',
      phone: u.phone || '',
      process_ids: u.process_ids || '',
      password: '',
      position_id: u.position_id || ''
    }
    modalEdit.value = true
    modalId.value = u.id
    processDropdownOpen.value = false
    processSearch.value = ''
    const ids = (u.process_ids || '').split(',').map(x => parseInt(x.trim())).filter(x => !isNaN(x))
    selectedProcessIds.value = ids
    showModal.value = true
  }

  async function save() {
    if (saving.value) return
    if (!form.value.username.trim() || !form.value.name.trim()) {
      showToast('用户名和姓名不能为空', 'error')
      return
    }
    if (!modalEdit.value && (!form.value.password || form.value.password.length < 6)) {
      showToast('新员工密码至少需要6位', 'error')
      return
    }
      saving.value = true
      try {
        const data = { ...form.value }
      data.role = data.role || 'worker'
        if (!data.password) delete data.password
        if (!data.email) delete data.email
        if (!data.phone) delete data.phone
        if (!data.employee_no) delete data.employee_no
      if (!modalEdit.value && !data.process_ids) delete data.process_ids
      if (data.position_id === '' || data.position_id === null || data.position_id === undefined) {
        if (modalEdit.value) data.position_id = null
        else delete data.position_id
      } else {
        data.position_id = parseInt(data.position_id)
      }
      if (modalEdit.value) {
        delete data.username
        await api.domains.users.updateUser(modalId.value, data)
        showToast('更新成功')
      } else {
        await api.domains.users.createUser(data)
        showToast('创建成功')
      }
      showModal.value = false
      await load()
    } catch(e) {
      if (e.code === 409) {
        showToast('用户名已存在', 'error')
      } else {
        showToast(e.message || '保存失败', 'error')
      }
    } finally {
      saving.value = false
    }
  }

  async function del(u) {
    if (!confirm('确定删除员工 "' + u.name + '" 吗？')) return
    try {
      await api.domains.users.deleteUser(u.id)
      showToast('删除成功')
      await load()
    } catch(e) {
      showToast(e.message || '删除失败', 'error')
    }
  }

  async function restoreUser(u) {
    if (!confirm('确定恢复员工 "' + u.name + '" 吗？')) return
    try {
      await api.domains.users.restoreUser(u.id)
      showToast('恢复成功')
      await load()
    } catch (e) {
      showToast(e.message || '恢复失败', 'error')
    }
  }

  async function purgeUser(uid, name) {
    const reason = prompt(
      '请输入匿名化原因（至少4个字符）。身份信息会清除，工资、绩效和审计历史继续保留：',
      ''
    )
    if (reason === null) return
    if (reason.trim().length < 4) {
      showToast('匿名化原因至少需要4个字符', 'error')
      return
    }
    if (!confirm('确认匿名化员工 "' + name + '" 的身份信息？此操作不可恢复。')) return
    try {
      await api.domains.users.permanentDeleteUser(uid, { reason: reason.trim() })
      showToast('身份已匿名化，历史记录已保留')
      await load()
    } catch(e) {
      showToast(e.message || '匿名化失败', 'error')
    }
  }

  async function resetPwd(u) {
    const pw = prompt('请输入新密码（至少8位，需包含字母和数字）：', '')
    if (pw === null) return
    if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) {
      showToast('新密码至少8位，且必须包含字母和数字', 'error')
      return
    }
    try {
      await api.domains.users.resetPassword(u.id, { password: pw })
      showToast('密码已重置')
    } catch(e) {
      showToast(e.message || '重置失败', 'error')
    }
  }

  async function unlock(u) {
    if (!confirm('确定解锁账户 "' + u.name + '" 吗？')) return
    try {
      await api.domains.users.unlockUser(u.id)
      showToast('账户已解锁')
      await load()
    } catch(e) {
      showToast(e.message || '解锁失败', 'error')
    }
  }

  onMounted(() => load())

  return {
    users, positions, loading, searchKeyword,
    showModal, modalEdit, form, canCreate, canEdit, canDelete, canAdmin,
    activeCount, inactiveCount, deletedCount, totalStaff,
    processes, processDropdownOpen, processSearch, selectedProcessIds, filteredProcessList, selectedProcessNames, onProcessChange, dropdownStyle, toggleProcessDropdown,
    page, total, pageSize,
    getPositionName, positionMap, getWorkProcesses, getWorkProcessTitle,
    saving, openAdd, openEdit, save, del, restoreUser, purgeUser, resetPwd, unlock, load, searchAndLoad,
    prevPage, nextPage
  }
}
