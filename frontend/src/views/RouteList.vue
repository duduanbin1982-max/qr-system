<!-- RouteList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🔀</span><div><div class="s-val">{{ total || routes.length }}</div><div class="s-label">路线总数</div></div></div>
      <div class="summary-item"><span class="s-icon">🔩</span><div><div class="s-val text-primary">{{ routes.filter(r=>r.category==='结构件').length }}</div><div class="s-label">结构件路线</div></div></div>
      <div class="summary-item"><span class="s-icon">⚙️</span><div><div class="s-val text-success">{{ routes.filter(r=>r.category==='机加工').length }}</div><div class="s-label">机加工路线</div></div></div>
      <div class="summary-item"><span class="s-icon">📊</span><div><div class="s-val text-warning">{{ routes.reduce((s,r)=>s+(r.processes||[]).length,0) }}</div><div class="s-label">工序节点</div></div></div>
    </div>

    <!-- 分类Tab按钮 -->
    <div class="cat-tabs">
      <span class="cat-tab cat-tab-all" :class="{active: activeCat==='all'}" @click="switchCat('all')">📋 全部工序路线</span>
      <span class="cat-tab cat-tab-struct" :class="{active: activeCat==='结构件'}" @click="switchCat('结构件')">🔩 结构件路线</span>
      <span class="cat-tab cat-tab-mach" :class="{active: activeCat==='机加工'}" @click="switchCat('机加工')">⚙️ 机加工路线</span>
    </div>

    <!-- 搜索栏 -->
    <div class="toolbar-row">
      <div style="flex:1;min-width:200px;position:relative">
        <input class="form-input" v-model="searchKeyword" @keyup.enter="searchAndLoad" placeholder="🔍 搜索路线名称..." style="padding-left:36px">
        <span v-if="searchKeyword" @click="searchKeyword='';searchAndLoad()" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);cursor:pointer;color:var(--text-placeholder);font-size:14px">✕</span>
      </div>
      <button class="btn btn-default btn-sm" @click="searchAndLoad" style="white-space:nowrap">搜索</button>
      <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openAdd" style="white-space:nowrap">+ 新建路线</button>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>🔀 工序路线</h3>
        <span style="color:var(--text-placeholder);font-size:var(--text-sm)">共 {{ total || routes.length }} 项</span>
      </div>
      <div class="card-body">
        <div v-if="routes.length">
          <div v-for="(r, idx) in routes" :key="r.id" class="route-card" style="border:1px solid var(--border-light);border-radius:var(--radius-lg);padding:var(--space-4);margin-bottom:var(--space-3);background:white">
            <div style="display:flex;align-items:center;justify-content:space-between;cursor:pointer" @click="toggleExpand(r.id)">
              <div style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap">
                <span style="display:inline-flex;width:28px;height:28px;border-radius:50%;background:var(--primary-light);color:var(--primary);align-items:center;justify-content:center;font-weight:bold;font-size:13px;flex-shrink:0">{{ idx + 1 }}</span>
                <span style="font-size:var(--text-xl)">{{ expandedId === r.id ? '▼' : '▶' }}</span>
                <div>
                  <div style="font-weight:600;font-size:15px">{{ r.name }}</div>
                  <div v-if="r.description" style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">{{ r.description }}</div>
                </div>
                <span v-for="cat in routeCategories(r)" :key="cat" class="badge" :class="cat==='结构件'?'badge-info':'badge-warning'" style="font-size:var(--text-2xs)">{{ cat }}</span>
                <span class="badge" :class="r.status==='active'?'badge-success':'badge-danger'" style="font-size:var(--text-xs-alt)">{{ r.status==='active'?'启用':'停用' }}</span>
              </div>
              <div style="display:flex;gap:var(--space-1)" @click.stop>
                <span v-if="canEdit" class="o-abtn o-edit" @click="openEdit(r)" title="编辑">✏️</span>
                <span v-if="canDelete" class="o-abtn o-del" @click="del(r)" title="删除">🗑️</span>
              </div>
            </div>
            <!-- 工序流 -->
            <div v-if="r.processes && r.processes.length" style="display:flex;align-items:center;gap:0;margin-top:8px;flex-wrap:wrap">
              <template v-for="(p, idx) in r.processes" :key="p.id">
                <span style="display:flex;align-items:center;gap:var(--space-1);background:var(--primary-light);border:1px solid var(--primary-light);border-radius:var(--radius-md);padding:var(--space-1) 10px;font-size:var(--text-xs);white-space:nowrap">
                  <span style="color:var(--primary);font-weight:600">{{ idx + 1 }}</span>
                  <span>{{ p.process_name }}</span>
                  <span v-if="p.required_audit" style="color:var(--warning);font-size:var(--text-2xs)" title="需要审批">🔒</span>
                </span>
                <span v-if="idx < r.processes.length - 1" style="color:var(--text-placeholder);margin:0 2px">→</span>
              </template>
            </div>
            <!-- 展开详情 -->
            <div v-if="expandedId === r.id && r.processes && r.processes.length" style="margin-top:12px;border-top:1px solid var(--bg-hover);padding-top:12px">
              <table class="data-table text-xs">
                <thead><tr><th class="col-num">#</th><th>工序名称</th><th class="col-small">序号</th><th class="col-small">必须</th><th class="col-small">审批</th></tr></thead>
                <tbody>
                  <tr v-for="(p, idx) in r.processes" :key="p.id">
                    <td class="text-center">{{ idx + 1 }}</td>
                    <td>{{ p.process_name }}</td>
                    <td class="text-center">{{ p.seq_order }}</td>
                    <td class="text-center">{{ p.is_required ? '✅' : '-' }}</td>
                    <td class="text-center">{{ p.required_audit ? '🔒' : '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="!r.processes || !r.processes.length" style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:8px">暂无工序节点</div>
          </div>
        </div>
        <div v-else class="empty"><div class="empty-icon">🔀</div><div class="empty-text">{{ routes.length ? '无匹配路线' : '暂无工序路线' }}</div></div>
        <!-- 分页 -->
        <div v-if="total > pageSize" class="pagination-bar">
          <button class="btn btn-sm btn-default" :disabled="page <= 1" @click="prevPage">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页 (共 {{ total }} 条)</span>
          <button class="btn btn-sm btn-default" :disabled="page * pageSize >= total" @click="nextPage">下一页</button>
        </div>
      </div>
    </div>

    <!-- 新增/编辑模态框 -->
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal" style="max-width:650px">
        <div class="modal-header">
          <span>{{ modalEdit ? '编辑路线' : '新建路线' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col" style="flex:2"><div class="form-group"><label>路线名称 *</label><input class="form-input" v-model="form.name" placeholder="如：标准结构件路线"></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>分类</label>
              <select class="form-input" v-model="form.category">
                <option value="结构件">结构件</option>
                <option value="机加工">机加工</option>
              </select></div></div>
          </div>
          <div class="form-group"><label>描述</label><textarea class="form-input" v-model="form.description" rows="2" placeholder="路线描述"></textarea></div>

          <!-- 工序节点编辑器 -->
          <div style="margin-top:16px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-2)">
              <label style="font-weight:600;font-size:var(--text-base)">工序节点</label>
              <button class="btn btn-default btn-sm" @click="addRow" style="font-size:var(--text-xs);padding:var(--space-1) 12px">+ 添加工序</button>
            </div>
            <div v-if="routeProcesses.length">
              <div v-for="(rp, idx) in routeProcesses" :key="idx" style="display:flex;gap:var(--space-2);align-items:center;margin-bottom:6px;padding:var(--space-2);background:var(--bg-table-header);border-radius:var(--radius-md)">
                <span style="color:var(--text-placeholder);font-size:var(--text-xs);min-width:20px">{{ idx + 1 }}</span>
                <select class="form-input" v-model="rp.process_id" style="flex:1;font-size:var(--text-sm)">
                  <option value="">-- 选择工序 --</option>
                  <option v-for="p in allProcesses" :key="p.id" :value="p.id">{{ p.seq_order }}. {{ p.process_name }}</option>
                </select>
                <label style="display:flex;align-items:center;gap:var(--space-1);font-size:var(--text-xs);white-space:nowrap;color:var(--text-placeholder)">
                  <input type="checkbox" v-model="rp.required_audit" :true-value="1" :false-value="0" style="accent-color:var(--primary)"> 需审批
                </label>
                <span @click="removeRow(idx)" style="color:var(--danger);cursor:pointer;font-size:var(--text-base)" title="移除">✕</span>
              </div>
            </div>
            <p v-else style="font-size:var(--text-xs);color:var(--text-placeholder);text-align:center;padding:var(--space-3)">暂未添加工序节点</p>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can, auth } from '@/lib/auth.js'

export default {
  setup() {
    const routes = ref([])
    const loading = ref(true)
    const allProcesses = ref([])
    const expandedId = ref(null)

    const searchKeyword = ref('')
    const page = ref(1)
    const pageSize = ref(20)
    const total = ref(0)

    const canCreate = computed(() => can('routes:create'))
    const canEdit   = computed(() => can('routes:edit'))
    const canDelete = computed(() => can('routes:delete'))

    const categoryFilter = ref('')
    const activeCat = computed(() => {
      if (!categoryFilter.value) return 'all'
      return categoryFilter.value
    })

    function switchCat(cat) {
      categoryFilter.value = cat === 'all' ? '' : cat
      page.value = 1
      load()
    }

    function searchAndLoad() {
      page.value = 1
      load()
    }

    function prevPage() { if (page.value > 1) { page.value--; load() } }
    function nextPage() {
      if (page.value * pageSize.value < total.value) { page.value++; load() }
    }

    // 收集路线涉及的所有工序 category (用于前端汇总显示)
    function routeCategories(r) {
      if (!r.processes || !r.processes.length) return []
      const cats = new Set()
      for (const p of r.processes) {
        if (p.category) cats.add(p.category)
      }
      return [...cats]
    }

    // 模态框
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ name:'', description:'', category:'结构件' })
    const routeProcesses = ref([])

    async function load() {
      loading.value = true
      try {
        const params = {}
        if (categoryFilter.value) params.category = categoryFilter.value
        if (searchKeyword.value.trim()) params.search = searchKeyword.value.trim()
        params.limit = pageSize.value
        params.offset = (page.value - 1) * pageSize.value
        const d = await api.listProcessRoutes(params)
        routes.value = d.routes || []
        total.value = d.total || 0
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }

    const processMap = computed(() => {
      const m = {}
      for (const p of allProcesses.value) { m[p.id] = p.process_name }
      return m
    })

    async function loadProcesses() {
      try { const d = await api.listProcesses(); allProcesses.value = d.processes || [] } catch(e) { showToast('加载工序列表失败', 'warn') }
    }

    function toggleExpand(id) { expandedId.value = expandedId.value === id ? null : id }

    function openAdd() {
      form.value = { name:'', description:'', category:'结构件' }
      routeProcesses.value = []
      modalEdit.value = false; modalId.value = null
      showModal.value = true
    }

    function openEdit(r) {
      form.value = { name: r.name || '', description: r.description || '', category: r.category || '结构件' }
      routeProcesses.value = (r.processes || []).map(p => ({
        process_id: p.process_id,
        required_audit: p.required_audit || 0
      }))
      modalEdit.value = true; modalId.value = r.id
      showModal.value = true
    }

    function addRow() {
      routeProcesses.value.push({ process_id: '', required_audit: 0 })
    }

    function removeRow(idx) {
      routeProcesses.value.splice(idx, 1)
    }

    function getProcessName(pid) {
      return processMap.value[pid] || ''
    }

    async function save() {
      if (!form.value.name.trim()) { showToast('请输入路线名称','error'); return }
      try {
        const data = {
          name: form.value.name.trim(),
          description: form.value.description,
          category: form.value.category,
          processes: routeProcesses.value.filter(p => p.process_id !== '')
        }
        if (modalEdit.value) {
          await api.updateProcessRoute(modalId.value, data)
          showToast('更新成功')
        } else {
          await api.createProcessRoute(data)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }

    async function del(r) {
      let impactMsg = ''
      try {
        const res = await api.getRouteImpact(r.id)
        if (res.used_orders > 0) {
          impactMsg = '\n\n' + res.used_orders + ' 个订单正在使用此路线'
        }
      } catch(e) {
        showToast(e.message || '检查路线使用情况失败，将继续删除确认', 'warn')
      }
      if (!confirm('确定删除路线 "' + r.name + '" 吗？' + impactMsg + '\n此操作不可恢复！')) return
      try { await api.deleteProcessRoute(r.id); showToast('删除成功'); await load() }
      catch(e) { showToast(e.message || '删除失败', 'error') }
    }

    onMounted(async () => { await loadProcesses(); load() })

    return {
      routes, loading, expandedId, toggleExpand, allProcesses,
      showModal, modalEdit, form, routeProcesses, canCreate, canEdit, canDelete,
      openAdd, openEdit, addRow, removeRow, getProcessName, save, del,
      routeCategories, searchKeyword, searchAndLoad,
      categoryFilter, activeCat, switchCat,
      page, pageSize, total, prevPage, nextPage,
    }
  }
}
</script>
