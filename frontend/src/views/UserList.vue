<!-- UserList.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- 统计栏 -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val">{{ totalStaff }}</div><div class="s-label">员工总数</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ activeCount }}</div><div class="s-label">在职</div></div></div>
      <div class="summary-item"><span class="s-icon">⏸️</span><div><div class="s-val text-danger">{{ inactiveCount }}</div><div class="s-label">停用</div></div></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>👷 普通员工管理</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <div style="position:relative;flex:1;max-width:280px">
            <input class="form-input" v-model="searchKeyword" @keyup.enter="searchAndLoad" placeholder="🔍 搜索用户名/姓名/工号..." style="padding-left:34px">
            <span v-if="searchKeyword" @click="searchKeyword='';searchAndLoad()" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);cursor:pointer;color:var(--text-placeholder);font-size:14px">✕</span>
          </div>
          <button class="btn btn-sm" @click="searchAndLoad" style="background:var(--border-light)">搜索</button>
          <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openAdd">+ 添加员工</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="users.length" class="data-table table-wide">
            <thead>
              <tr>
                <th class="col-num">#</th>
                <th class="col-min-80">用户名</th>
                <th class="col-min-70">姓名</th>
                <th class="col-min-70">岗位</th>
                <th class="col-cat">工号</th>
                <th class="col-min-100">手机号</th>
                <th class="col-status">状态</th>
                <th class="col-actions-wide">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(u, idx) in users" :key="u.id">
                <td class="text-center"><span class="row-num">{{ idx + 1 }}</span></td>
                <td><code style="font-size:var(--text-xs)">{{ u.username }}</code></td>
                <td class="fw-500">{{ u.name || '-' }}</td>
                <td><span class="badge badge-info" style="font-size:var(--text-xs-alt)">{{ getPositionName(u.position_id) }}</span></td>
                <td>{{ u.employee_no || '-' }}</td>
                <td class="text-sm">{{ u.phone || '-' }}</td>
                <td><span class="badge" :class="u.status === 'active' ? 'badge-success' : 'badge-danger'" style="font-size:var(--text-xs-alt)">{{ u.status === 'active' ? '在职' : '停用' }}</span></td>
                <td class="text-center">
                  <div class="o-actions" style="justify-content:center">
                    <span v-if="u.locked_until && canEdit" class="o-abtn" style="color:var(--danger);cursor:pointer" @click="unlock(u)" title="解锁账户">🔓</span>
                    <span v-if="canEdit" class="o-abtn o-edit" @click="openEdit(u)" title="编辑">✏️</span>
                    <span v-if="canEdit" class="o-abtn" style="color:var(--warning);cursor:pointer" @click="resetPwd(u)" title="重置密码">🔑</span>
                    <span v-if="canDelete" class="o-abtn o-del" @click="del(u)" title="删除">🗑️</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-icon">👥</div><div class="empty-text">{{ searchKeyword ? '未找到匹配的员工' : '暂无员工数据' }}</div></div>
        </div>
        <div v-if="total > pageSize" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-3) 16px;border-top:1px solid var(--border)">
          <button class="btn btn-sm btn-default" :disabled="page<=1" @click="prevPage">‹ 上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total/pageSize) }} 页（共 {{ total }} 条）</span>
          <button class="btn btn-sm btn-default" :disabled="page * pageSize >= total" @click="nextPage">下一页 ›</button>
        </div>
      </div>
    </div>

    <!-- 新增/编辑模态框 -->
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal" style="display:flex;flex-direction:column;max-width:520px;min-width:420px;max-height:82vh;overflow:hidden">
        <div class="modal-header" style="flex-shrink:0">
          <span>{{ modalEdit ? '编辑员工' : '添加员工' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body" style="flex:1;overflow-y:auto;padding:var(--space-5) var(--space-6)">
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>用户名 *</label><input class="form-input" v-model="form.username" :disabled="modalEdit" :placeholder="modalEdit ? '(不可修改)' : '登录用户名'"></div>
            </div>
            <div class="form-col">
              <div class="form-group"><label>姓名 *</label><input class="form-input" v-model="form.name" placeholder="真实姓名"></div>
            </div>
          </div>
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>工号</label><input class="form-input" v-model="form.employee_no" placeholder="留空自动生成4位顺序号"></div>
            </div>

          </div>
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>手机号</label><input class="form-input" v-model="form.phone" placeholder="联系电话"></div>
            </div>
            <div class="form-col">
              <div class="form-group"><label>岗位</label>
                <select class="form-input" v-model="form.position_id">
                  <option value="">未分配</option>
                  <option v-for="pos in positions" :key="pos.id" :value="pos.id">{{ pos.name }}</option>
                </select>
              </div>
            </div>
          </div>
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>状态</label>
                <select class="form-input" v-model="form.status">
                  <option value="active">正常</option>
                  <option value="inactive">停用</option>
                </select>
              </div>
            </div>
            <div class="form-col">
              <div class="form-group"><label>密码{{ modalEdit ? '' : ' *' }}</label><input class="form-input" type="password" v-model="form.password" :placeholder="modalEdit ? '留空不修改' : '留空则自动生成'"></div>
            </div>
          </div>
          <div class="form-group" style="position:relative">
            <label>工序</label>
            <div class="multi-select-trigger form-input" @click.stop="toggleProcessDropdown" style="cursor:pointer;display:flex;align-items:center;justify-content:space-between">
              <span v-if="selectedProcessIds.length === 0" style="color:var(--text-placeholder)">选择工序...</span>
              <span v-else style="font-size:var(--text-sm)">已选 {{ selectedProcessIds.length }} 个工序</span>
              <span style="font-size:12px">{{ processDropdownOpen ? '▲' : '▼' }}</span>
            </div>
            <div v-if="processDropdownOpen" class="multi-select-dropdown" :style="dropdownStyle" style="position:fixed;z-index:9999;background:white;border:1px solid var(--border);border-radius:var(--radius-md);max-height:260px;overflow-y:auto;box-shadow:0 8px 24px rgba(0,0,0,0.18)">
              <div style="padding:8px;position:sticky;top:0;background:white;border-bottom:1px solid var(--border-light);z-index:1">
                <input class="form-input" v-model="processSearch" placeholder="搜索工序..." style="font-size:var(--text-sm);padding:6px 8px" @click.stop>
              </div>
              <div style="padding:4px 8px">
                <label v-for="p in filteredProcessList" :key="p.id" style="display:flex;align-items:center;gap:8px;padding:6px 8px;cursor:pointer;border-radius:var(--radius-sm);font-size:var(--text-sm)" @click.stop>
                  <input type="checkbox" :value="p.id" v-model="selectedProcessIds" @change="onProcessChange" style="cursor:pointer">
                  <span>{{ p.process_name }}</span>
                  <span style="color:var(--text-placeholder);font-size:var(--text-xs);margin-left:auto">{{ p.category }}</span>
                </label>
                <div v-if="filteredProcessList.length === 0" style="padding:12px;text-align:center;color:var(--text-placeholder);font-size:var(--text-sm)">无匹配工序</div>
              </div>
              <div v-if="selectedProcessIds.length > 0" style="padding:8px;border-top:1px solid var(--border-light);display:flex;gap:6px;position:sticky;bottom:0;background:white">
                <button class="btn btn-sm" style="background:var(--bg-hover);font-size:var(--text-xs)" @click.stop="selectedProcessIds=[];onProcessChange()">清除全部</button>
                <button class="btn btn-sm btn-primary" style="font-size:var(--text-xs);margin-left:auto" @click.stop="processDropdownOpen=false">确定</button>
              </div>
            </div>
            <div v-if="selectedProcessNames.length > 0" style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px">
              <span v-for="n in selectedProcessNames" :key="n.id" style="display:inline-block;padding:2px 8px;background:var(--primary-light);border-radius:var(--radius-sm);font-size:var(--text-xs);color:var(--primary)">{{ n.name }}</span>
            </div>
          </div>
        </div>
        <!-- 创建成功密码展示面板 -->
        <div v-if="pwResult" style="margin:var(--space-3) var(--space-5);padding:var(--space-4);background:#f0fdf4;border:1px solid #86efac;border-radius:var(--radius-md)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-2)">
            <strong style="color:#166534">✅ {{ pwResult.name }} 创建成功</strong>
            <span @click="pwResult=null" style="cursor:pointer;font-size:18px;color:var(--text-placeholder)">&times;</span>
          </div>
          <div style="font-size:var(--text-sm);color:#14532d;line-height:1.8">
            <div>用户名：<code style="background:#dcfce7;padding:2px 6px;border-radius:3px">{{ pwResult.username }}</code></div>
            <div>随机密码：<code style="background:#dcfce7;padding:2px 6px;border-radius:3px;font-weight:bold">{{ pwResult.password }}</code></div>
          </div>
          <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:var(--space-2)">请将密码告知员工，首次登录需修改密码</div>
        </div>

        <div class="modal-footer" style="flex-shrink:0">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save" :disabled="saving">{{ saving ? "保存中..." : "保存" }}</button>
        </div>
      </div>
    </div>

</div></template>

<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export default {
  setup() {
    const users = ref([])
    const positions = ref([])
    const processes = ref([])
    const processDropdownOpen = ref(false)
    const dropdownStyle = ref({})
    const pwResult = ref(null)
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
          const result = await api.createUser(data)
          if (result.password) {
            showModal.value = false
            await load()
            const pwMsg = '员工 ' + form.value.name + ' 创建成功！\n\n' +
                '用户名: ' + form.value.username + '\n' +
                '随机密码: ' + result.password + '\n\n' +
                '请将密码告知员工，首次登录需修改密码。'
            alert(pwMsg)
            showToast(form.value.name + ' 已创建，密码 ' + result.password)
            return
          }
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
      saving, pwResult, openAdd, openEdit, save, del, resetPwd, unlock, load, searchAndLoad,
      prevPage, nextPage
    }
  }
}
</script>
