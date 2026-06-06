// ProcessList Component — 工序管理
import { ref, onMounted, computed, watch } from '../../vendor/vue.esm.js'
import { api } from '../../api.js'
import { showToast } from '../../store.js'
import { auth, can } from '../../auth.js'
import { router } from '../../router.js'

export default {
  template: '#process-list-template',
  setup() {
    const processes = ref([])
    const loading = ref(true)
    const filterCategory = ref('')
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
      load()
    }

    // 页面标题
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
    const canDelete = computed(() => can('processes:delete'))

    async function load() {
      loading.value = true
      try {
        const params = {}
        if (filterCategory.value) params.category = filterCategory.value
        const d = await api.listProcesses(Object.keys(params).length ? params : null)
        processes.value = d.processes || []
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
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
        seq_order: p.seq != null ? String(p.seq) : '',
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
      if (!confirm('确定删除工序 "' + p.process_name + '" 吗？\n关联的路线明细、工价、报工记录、物料消耗等数据也将一并清除。')) return
      try {
        await api.deleteProcess(p.id)
        showToast('删除成功')
        await load()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }

    onMounted(() => {
      filterCategory.value = categoryFromPage(router.page)
      load()
    })

    // 监听路由变化，切换分类并重新加载
    watch(() => router.page, (page) => {
      const cat = categoryFromPage(page)
      if (filterCategory.value !== cat) {
        filterCategory.value = cat
        load()
      }
    })

    return {
      processes, loading, filterCategory, pageTitle, load,
      showModal, modalEdit, form, categories,
      structCount, machCount, auth, can, canEdit, canDelete,
      openAdd, openEdit, save, del, activeCat, switchCat
    }
  }
}
