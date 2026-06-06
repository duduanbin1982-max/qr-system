// RouteList Component — 工序路线
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { auth, can } from '../../auth.js?v=56'

export default {
  template: '#route-list-template',
  setup() {
    const routes = ref([])
    const loading = ref(true)
    const allProcesses = ref([])
    const expandedId = ref(null)

    const categoryFilter = ref('')
    const activeCat = computed(() => {
      if (!categoryFilter.value) return 'all'
      return categoryFilter.value
    })

    // filteredRoutes 从后端筛选后直接返回（不再客户端过滤）
    const filteredRoutes = computed(() => routes.value)

    function switchCat(cat) {
      categoryFilter.value = cat === 'all' ? '' : cat
      load()
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
        const d = await api.listProcessRoutes(Object.keys(params).length ? params : null)
        routes.value = d.routes || []
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }

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
      const p = allProcesses.value.find(x => x.id == pid)
      return p ? p.process_name : ''
    }

    async function save() {
      if (!form.value.name.trim()) { showToast('请输入路线名称','error'); return }
      try {
        const data = {
          name: form.value.name.trim(),
          description: form.value.description,
          category: form.value.category,
          processes: routeProcesses.value.filter(p => p.process_id)
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
      if (!confirm('确定删除路线 "' + r.name + '" 吗？')) return
      try { await api.deleteProcessRoute(r.id); showToast('删除成功'); await load() }
      catch(e) { showToast(e.message || '删除失败', 'error') }
    }

    onMounted(async () => { await loadProcesses(); load() })

    return {
      routes, loading, expandedId, toggleExpand, allProcesses,
      showModal, modalEdit, form, routeProcesses,
      openAdd, openEdit, addRow, removeRow, getProcessName, save, del, auth,
      categoryFilter, activeCat, switchCat, filteredRoutes,
    }
  }
}
