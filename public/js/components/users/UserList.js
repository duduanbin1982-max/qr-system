// UserList Component — 员工管理（参照index.html完善）
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { can } from '../../auth.js?v=56'

export default {
  template: '#user-list-template',
  setup() {
    const users = ref([])
    const positions = ref([])
    const loading = ref(true)
    const searchKeyword = ref('')
    const page = ref(1)
    const total = ref(0)
    const pageSize = 20

    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({
      username: '', name: '', nickname: '', email: '',
      status: 'active',
      employee_no: '', phone: '', process_ids: '', password: '',
      position_id: ''
    })

    const roles = [
      { value: 'admin', label: '管理员' },
      { value: 'worker', label: '员工' }
    ]

    // RBAC 权限控制
    const canCreate = computed(() => can('users:create'))
    const canEdit = computed(() => can('users:edit'))
    const canDelete = computed(() => can('users:delete'))

    // P1-1: 统计口径统一（不含管理员）
    const activeCount = computed(() => users.value.filter(u => u.role !== 'admin' && u.status === 'active').length)
    const inactiveCount = computed(() => users.value.filter(u => u.role !== 'admin' && u.status !== 'active').length)
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
        const [userData, posData] = await Promise.all([
          api.listUsers({ page: page.value, limit: pageSize, keyword: searchKeyword.value }),
          api.listPositions()
        ])
        users.value = userData.users || []
        total.value = userData.total || 0
        positions.value = posData.positions || []
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

    const filteredUsers = computed(() => {
      return users.value.filter(u => u.role !== 'admin' && !u.has_admin_role)
    })

    function openAdd() {
      form.value = {
        username: '', name: '', nickname: '', email: '',
        status: 'active',
        employee_no: '', phone: '', process_ids: '', password: '',
        position_id: ''
      }
      modalEdit.value = false
      modalId.value = null
      showModal.value = true
    }

    function openEdit(u) {
      form.value = {
        username: u.username || '',
        name: u.name || '',
        nickname: u.nickname || '',
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
      showModal.value = true
    }

    async function save() {
      if (!form.value.username.trim() || !form.value.name.trim()) {
        showToast('用户名和姓名不能为空', 'error')
        return
      }
      try {
        const data = { ...form.value }
        if (modalEdit.value) {
          delete data.username
          if (!data.password) delete data.password
        }
        if (data.position_id === '' || data.position_id === null || data.position_id === undefined) {
          data.position_id = null
        } else {
          data.position_id = parseInt(data.position_id)
        }
        if (modalEdit.value) {
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
      }
    }

    async function del(u) {
      if (!confirm('确定删除员工 "' + (u.nickname || u.name) + '" 吗？')) return
      try {
        await api.deleteUser(u.id)
        showToast('删除成功')
        await load()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }

    async function resetPwd(u) {
      const pw = prompt('请输入新密码（默认 123456）：', '123456')
      if (!pw) return
      try {
        await api.resetPassword(u.id, { password: pw })
        showToast('密码已重置')
      } catch(e) {
        showToast(e.message || '重置失败', 'error')
      }
    }

    async function unlock(u) {
      if (!confirm('确定解锁账户 "' + (u.nickname || u.name) + '" 吗？')) return
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
      users, positions, loading, searchKeyword, filteredUsers,
      showModal, modalEdit, form, roles, canCreate, canEdit, canDelete,
      activeCount, inactiveCount, totalStaff,
      page, total, pageSize,
      getPositionName, positionMap,
      openAdd, openEdit, save, del, resetPwd, unlock, load, searchAndLoad,
      prevPage, nextPage
    }
  }
}
