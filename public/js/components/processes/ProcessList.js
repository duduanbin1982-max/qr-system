// ProcessList Component — 工序管理
import { ref, onMounted, computed, watch } from '../../vendor/vue.esm.js'
import { api } from '../../api.js'
import { showToast } from '../../store.js'
import { can } from '../../auth.js'
import { router } from '../../router.js'

export default {
  template: '#process-list-template',
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
      filterCategory.value = cat === 'all' ? '' : cat
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

    const structCount = computed(() => processes.value.filter(p => p.category === '结构件').length)
    const machCount   = computed(() => processes.value.filter(p => p.category === '机加工').length)

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
        processes.value = d.processes || []
        total.value = d.total || 0
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
          seq_order: form.value.seq_order ? parseInt(form.value.seq_order) : undefined,
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
      var impactMsg = ''
      try {
        var impactRes = await api.get('/api/processes/' + p.id + '/impact')
        var impact = impactRes.impact || {}
        var labels = { work_records:'报工记录', scrap_records:'报废记录', rework_records:'返工记录',
          quality_inspections:'质检记录', process_prices:'工价记录', process_route_items:'路线工序关联',
          order_processes:'订单工序关联', position_processes:'岗位工序关联', material_consumptions:'物料消耗' }
        var keys = Object.keys(impact)
        if (keys.length > 0) {
          impactMsg = '\n\n将级联删除以下数据：\n'
          for (var i = 0; i < keys.length; i++) {
            impactMsg += '  - ' + (labels[keys[i]] || keys[i]) + '：' + impact[keys[i]] + ' 条\n'
          }
        }
      } catch(e) {}
      if (!confirm('确定删除工序 "' + p.process_name + '" 吗？' + impactMsg + '\n此操作不可恢复！')) return
      try {
        await api.deleteProcess(p.id)
        showToast('删除成功')
        await load()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }

    // 监听路由变化，切换分类并重新加载
    watch(() => router.page, (page) => {
      const cat = categoryFromPage(page)
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
