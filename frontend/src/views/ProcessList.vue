<!-- ProcessList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">⚙️</span><div><div class="s-val">{{ processes.length }}</div><div class="s-label">工序总数</div></div></div>
      <div class="summary-item"><span class="s-icon">🏗️</span><div><div class="s-val text-primary">{{ structCount }}</div><div class="s-label">结构件</div></div></div>
      <div class="summary-item"><span class="s-icon">🔧</span><div><div class="s-val text-success">{{ machCount }}</div><div class="s-label">机加工</div></div></div>
    </div>

    <!-- 分类Tab按钮 -->
    <div class="cat-tabs">
      <span class="cat-tab cat-tab-all" :class="{active: activeCat==='all'}" @click="switchCat('all')">📋 全部工序</span>
      <span class="cat-tab cat-tab-struct" :class="{active: activeCat==='结构件'}" @click="switchCat('结构件')">🔩 结构件工序</span>
      <span class="cat-tab cat-tab-mach" :class="{active: activeCat==='机加工'}" @click="switchCat('机加工')">⚙️ 机加工工序</span>
    </div>

    <!-- 搜索栏 + 添加工序 -->
    <div class="toolbar-row" style="display:flex;gap:var(--space-3);margin-bottom:var(--space-4);align-items:center;flex-wrap:wrap">
      <div style="flex:1;min-width:200px;position:relative">
        <input class="form-input" v-model="searchKeyword" @keyup.enter="searchAndLoad" placeholder="🔍 搜索工序名称..." style="padding-left:36px">
        <span v-if="searchKeyword" @click="searchKeyword='';searchAndLoad()" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);cursor:pointer;color:var(--text-placeholder);font-size:14px">✕</span>
      </div>
      <button class="btn btn-default btn-sm" @click="searchAndLoad" style="white-space:nowrap">搜索</button>
      <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openAdd" style="white-space:nowrap">+ 添加工序</button>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>{{ pageTitle }}</h3>
        <span style="color:var(--text-placeholder);font-size:var(--text-sm)">共 {{ total || processes.length }} 项</span>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">
          <div style="font-size:32px;margin-bottom:8px">⏳</div>
          <div>加载中...</div>
        </div>
        <table v-else-if="processes.length" class="data-table">
            <thead>
              <tr>
                <th class="col-seq">序号</th>
                <th class="col-name">工序名称</th>
                <th>描述</th>
                <th class="col-cat">分类</th>
                <th class="col-status">状态</th>
                <th class="col-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(p, idx) in processes" :key="p.id">
                <td class="col-seq text-center"><span class="row-num">{{ (page - 1) * pageSize + idx + 1 }}</span></td>
                <td class="col-name fw-600">{{ p.process_name }}</td>
                <td class="text-muted text-sm">{{ p.description || '-' }}</td>
                <td class="col-cat nowrap"><span class="badge" :class="p.category === '结构件' ? 'badge-info' : 'badge-warning'" style="font-size:var(--text-xs-alt)">{{ p.category }}</span></td>
                <td class="col-status nowrap"><span class="badge" :class="p.status === 'active' ? 'badge-success' : 'badge-danger'" style="font-size:var(--text-xs-alt)">{{ p.status === 'active' ? '启用' : '停用' }}</span></td>
                <td class="col-actions text-center">
                  <div class="o-actions" style="justify-content:center">
                    <span v-if="canEdit" class="o-abtn o-edit" @click="openEdit(p)" title="编辑">✏️</span>
                    <span v-if="canDelete" class="o-abtn o-del" @click="del(p)" title="删除">🗑️</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else-if="!loading" class="empty"><div class="empty-icon">⚙️</div><div class="empty-text">暂无工序数据</div></div>
        </div>
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
      <div class="modal" style="max-width:500px">
        <div class="modal-header">
          <span>{{ modalEdit ? '编辑工序' : '添加工序' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-group"><label>工序名称 *</label><input class="form-input" v-model="form.name" placeholder="如：切割、焊接、喷涂"></div>
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>分类</label>
                <select class="form-input" v-model="form.category">
                  <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
                </select>
              </div>
            </div>
            <div class="form-col">
              <div class="form-group"><label>排序序号</label><input class="form-input" v-model="form.seq_order" type="number" placeholder="自动递增"></div>
            </div>
            <div class="form-col" v-if="modalEdit">
              <div class="form-group"><label>状态</label>
                <select class="form-input" v-model="form.status">
                  <option value="active">启用</option>
                  <option value="inactive">停用</option>
                </select>
              </div>
            </div>
          </div>
          <div class="form-group"><label>描述</label><textarea class="form-input" v-model="form.description" rows="2" placeholder="工序描述"></textarea></div>
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
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
import { router } from '@/lib/router.js'

export default {
  setup() {
    const processes = ref([])
    const loading = ref(true)
    const filterCategory = ref('')
    const searchKeyword = ref('')
    const activeCat = computed(() => {
      if (!filterCategory.value) return 'all'
      return filterCategory.value
    })

    // 根据当前路由页面确定分类筛选
    function categoryFromPage(page) {
      if (page === 'structure-processes') return '结构件'
      if (page === 'machining-processes') return '机加工'
      return '' // all-processes or processes → 全部
    }

    // Tab 切换分类
    function switchCat(cat) {
      const newCat = cat === 'all' ? '' : cat
      if (filterCategory.value === newCat) return
      filterCategory.value = newCat
      page.value = 1
      load()
    }

    function searchAndLoad() {
      page.value = 1
      load()
    }

    // 页面标题
    const page = ref(1)
    const pageSize = ref(20)
    const total = ref(0)

    const pageTitle = computed(() => {
      const cat = filterCategory.value
      if (cat === '结构件') return '🔩 结构件工序'
      if (cat === '机加工') return '⚙️ 机加工工序'
      return '📋 全部工序'
    })

    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ name: '', description: '', category: '结构件', seq_order: '', status: 'active' })

    const categories = ['结构件', '机加工']

    const structCount = ref(0)
    const machCount = ref(0)

    // RBAC 权限
    const canEdit   = computed(() => can('processes:edit'))
    const canCreate = computed(() => can('processes:create'))
    const canDelete = computed(() => can('processes:delete'))

    async function load() {
      loading.value = true
      try {
        const params = { sort_by: 'seq_order', sort_dir: 'asc' }
        if (filterCategory.value) params.category = filterCategory.value
        if (searchKeyword.value.trim()) params.search = searchKeyword.value.trim()
        params.limit = pageSize.value
        params.offset = (page.value - 1) * pageSize.value
        const d = await api.listProcesses(params)
        const data = d.processes || []
        processes.value = data
        total.value = d.total != null ? d.total : data.length
        if (d.category_counts) {
          structCount.value = d.category_counts['结构件'] || 0
          machCount.value = d.category_counts['机加工'] || 0
        }
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }

    function prevPage() { if (page.value > 1) { page.value--; load() } }
    function nextPage() {
      if (page.value * pageSize.value < total.value) { page.value++; load() }
    }

    function openAdd() {
      form.value = { name: '', description: '', category: '结构件', seq_order: '', status: 'active' }
      modalEdit.value = false
      modalId.value = null
      showModal.value = true
    }

    function openEdit(p) {
      // API returns process_name + seq; form uses name + seq_order
      form.value = {
        name: p.process_name || '',
        description: p.description || '',
        category: p.category || '结构件',
        seq_order: p.seq_order != null ? String(p.seq_order) : '',
        status: p.status || 'active'
      }
      modalEdit.value = true
      modalId.value = p.id
      showModal.value = true
    }

    async function save() {
      if (!form.value.name.trim()) {
        showToast('请输入工序名称', 'error')
        return
      }
      try {
        const data = {
          name: form.value.name.trim(),
          description: form.value.description,
          category: form.value.category,
          seq_order: form.value.seq_order != null && form.value.seq_order !== "" ? parseInt(form.value.seq_order) : undefined,
          status: form.value.status
        }
        if (data.seq_order === undefined) delete data.seq_order

        if (modalEdit.value) {
          await api.updateProcess(modalId.value, data)
          showToast('更新成功')
        } else {
          await api.createProcess(data)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }

    async function del(p) {
    try {
      const impactRes = await api.get('/api/processes/' + p.id + '/impact')
      const impact = impactRes.impact || {}
      const keys = Object.keys(impact)
      if (keys.length > 0) {
        const labels = { work_records:'报工记录', scrap_records:'报废记录', rework_records:'返工记录',
          quality_inspections:'质检记录', process_route_items:'路线工序关联',
          order_processes:'订单工序关联', position_processes:'岗位工序关联', material_consumptions:'物料消耗' }
        let detail = ''
        for (let i = 0; i < keys.length; i++) {
          detail += '\n  ' + (labels[keys[i]] || keys[i]) + '：' + impact[keys[i]] + ' 条'
        }
        showToast('该工序有关联数据，无法删除：' + detail, 'error')
        return
      }
    } catch(e) { showToast(e.message || '影响检查失败', 'error'); return }
    if (!confirm('确定删除工序 "' + p.process_name + '" 吗？\n此操作不可恢复！')) return
    try {
      await api.deleteProcess(p.id)
      showToast('删除成功')
      await load()
    } catch(e) {
      showToast(e.message || '删除失败', 'error')
    }
  }

    let _loadedOnce = false
    let _loadPromise = null

    // Initial load on mount
    onMounted(async () => {
      const cat = categoryFromPage(router.page)
      filterCategory.value = cat
      _loadedOnce = true
      // Retry up to 3 times if initial load fails
      for (let retry = 0; retry < 3; retry++) {
        try {
          await load()
          break
        } catch(e) {
          if (retry === 2) showToast('加载工序数据失败，请刷新重试', 'error')
          await new Promise(r => setTimeout(r, 1000 * (retry + 1)))
        }
      }
    })

    // 监听路由变化（跳过首次已加载的挂载）
    watch(() => router.page, (page) => {
      const cat = categoryFromPage(page)
      if (!_loadedOnce) {
        _loadedOnce = true
        return
      }
      if (filterCategory.value !== cat) {
        filterCategory.value = cat
        load()
      }
    })

    return {
      processes, loading, filterCategory, searchKeyword, pageTitle, load,
      showModal, modalEdit, form, categories,
      structCount, machCount, can, canCreate, canEdit, canDelete,
      openAdd, openEdit, save, del, activeCat, switchCat, searchAndLoad,
      page, pageSize, total, prevPage, nextPage
    }
  }
}
</script>
