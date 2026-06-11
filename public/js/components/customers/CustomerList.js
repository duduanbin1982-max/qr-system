// CustomerList Component — 客户管理
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { auth, can } from '../../auth.js'

export default {
  template: '#customer-list-template',
  setup() {
    const customers = ref([])
    const loading = ref(true)
    const searchKeyword = ref('')
    
    // 模态框状态
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ name:'', contact:'', phone:'', email:'', address:'', remark:'' })
    
    // 详情模态框
    const detail = ref(null)
    const detailOrders = ref([])
    const showDetail = ref(false)
    const deleteCheck = ref(null)       // 正在检查删除的客户
    const deleteCheckOrders = ref([])   // 该客户的活跃订单
    const showDeleteBlock = ref(false)  // 删除被阻止的弹窗
    
    // 统计
    const hasContact = computed(() => customers.value.filter(c => c.contact).length)
    const hasEmail = computed(() => customers.value.filter(c => c.email).length)

    // RBAC
    const canEdit   = computed(() => can('customers:edit'))
    const canDelete = computed(() => can('customers:delete'))
    const canCreate = computed(() => can('customers:create'))
    
    async function load() {
      loading.value = true
      try {
        const kw = searchKeyword.value.trim()
        const d = await api.listCustomers(kw ? { keyword: kw } : null)
        customers.value = d.customers || []
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }
    
    function openAdd() {
      form.value = { name:'', contact:'', phone:'', email:'', address:'', remark:'' }
      modalEdit.value = false
      modalId.value = null
      showModal.value = true
    }
    
    function openEdit(c) {
      form.value = { name:c.name, contact:c.contact||'', phone:c.phone||'', email:c.email||'', address:c.address||'', remark:c.remark||'' }
      modalEdit.value = true
      modalId.value = c.id
      showModal.value = true
    }
    
    async function save() {
      if (!form.value.name || !form.value.name.trim()) {
        showToast('请输入客户名称', 'error')
        return
      }
      try {
        if (modalEdit.value) {
          await api.updateCustomer(modalId.value, form.value)
          showToast('更新成功')
        } else {
          await api.createCustomer(form.value)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }
    
    async function del(c) {
      // 先查询客户关联的活跃订单
      deleteCheck.value = c
      deleteCheckOrders.value = []
      try {
        const d = await api.get('/api/customers/' + c.id + '/orders')
        const active = (d.orders || []).filter(o => o.deleted_at === null || o.deleted_at === undefined)
        if (active.length > 0) {
          deleteCheckOrders.value = active
          showDeleteBlock.value = true
          return
        }
      } catch(e) {
        // 查询失败，降级为直接确认删除
      }
      // 无活跃订单，确认后删除
      if (!confirm('确定删除客户 "' + c.name + '" 吗？\n\n该操作不可撤销。')) return
      try {
        await api.deleteCustomer(c.id)
        showToast('删除成功')
        await load()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }
    
    async function viewDetail(c) {
      detail.value = c
      showDetail.value = true
      try {
        const d = await api.get('/api/customers/' + c.id + '/orders')
        detailOrders.value = d.orders || []
      } catch(e) {
        detailOrders.value = []
      }
    }
    
    onMounted(() => load())
    
    return {
      customers, loading, searchKeyword, load,
      showModal, modalEdit, form, openAdd, openEdit, save, del,
      showDetail, detail, detailOrders, viewDetail,
      deleteCheck, deleteCheckOrders, showDeleteBlock,
      hasContact, hasEmail, can, canEdit, canDelete, canCreate
    }
  }
}
