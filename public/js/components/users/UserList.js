// UserList Component — 员工管理（参照index.html完善）
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { can } from '../../auth.js'

export default {
  template: '#user-list-template',
  setup() {
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
    const pageSize = 20

    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({
      username: '', name: '', email: '',
      status: 'active',
      employee_no: '', phone: '', process_ids: '', password: '',
      position_id: ''
    })


    // RBAC 权限控制
    const canCreate = computed(() => can('users:create'))
    const canEdit = computed(() => can('users:edit'))
    const canDelete = computed(() => can('users:delete'))

    // P1-1: 统计口径统一（不含管理员）
    const activeCount = computed(() => users.value.filter(u => u.status === 'active').length)
    const inactiveCount = computed(() => users.value.filter(u => u.status !== 'active').length)
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

    async function load() {
      loading.value = true
      try {
        const [userData, posData, procData] = await Promise.all([
          api.listUsers({ page: page.value, limit: pageSize, keyword: searchKeyword.value, role: 'worker' }),
          api.listPositions(),
          api.listProcesses()
        ])
        users.value = userData.users || []
        total.value = userData.total || 0
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
        employee_no: '', phone: '', process_ids: '', password: '',
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
      saving.value = true
      try {
        const data = { ...form.value }
        // 清理空值 — 防止 schema 校验拦截
        if (!data.password) delete data.password
        if (!data.email) delete data.email
        if (!data.phone) delete data.phone
        if (!data.employee_no) delete data.employee_no
        if (!data.process_ids) delete data.process_ids
        if (data.position_id === '' || data.position_id === null || data.position_id === undefined) {
          delete data.position_id
        } else {
          data.position_id = parseInt(data.position_id)
        }
        if (modalEdit.value) {
          delete data.username
          await api.updateUser(modalId.value, data)
          showToast('更新成功')
        } else {
          await api.createUser(data)
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
        await api.deleteUser(u.id)
        showToast('删除成功')
        await load()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }

    async function resetPwd(u) {
      const pw = prompt('请输入新密码（留空则随机生成）：', '')
      if (!pw) return
      try {
        await api.resetPassword(u.id, { password: pw })
        showToast('密码已重置')
      } catch(e) {
        showToast(e.message || '重置失败', 'error')
      }
    }

    async function unlock(u) {
      if (!confirm('确定解锁账户 "' + u.name + '" 吗？')) return
      try {
        await api.unlockUser(u.id)
        showToast('账户已解锁')
        await load()
      } catch(e) {
        showToast(e.message || '解锁失败', 'error')
      }
    }

    onMounted(() => load())

    return {
      users, positions, loading, searchKeyword,
      showModal, modalEdit, form, canCreate, canEdit, canDelete,
      activeCount, inactiveCount, totalStaff,
      processes, processDropdownOpen, processSearch, selectedProcessIds, filteredProcessList, selectedProcessNames, onProcessChange, dropdownStyle, toggleProcessDropdown,
      page, total, pageSize,
      getPositionName, positionMap,
      saving, openAdd, openEdit, save, del, resetPwd, unlock, load, searchAndLoad,
      prevPage, nextPage
    }
  }
}
