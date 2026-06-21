// OrderList Composable
import { ref, onMounted, watch, nextTick, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { handleApiError } from '@/lib/api.js'
import { useQrcode } from './useQrcode.js'
import { auth, can } from '@/lib/auth.js'

export function useOrder() {
const orders = ref([])
    const loading = ref(true)
    const total = ref(0)
    const page = ref(1)
    const limit = ref(20)
    const filterStatus = ref('')
    const searchKeyword = ref('')
    const filterCustomer = ref('')

    // ===== 下拉数据源 =====
    const customers = ref([])
    const products = ref([])
    const processRoutes = ref([])
    const productionLines = ref([])

    // 详情展开
    const expandedId = ref(null)

    // 模态框
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)

    const qr = useQrcode()

    // ===== 申请返工 =====

    // 申请返工
    function openRework(o) { reworkOrder.value = o; reworkForm.value = { process_id: "", quantity: 1, reason: "" }; showReworkModal.value = true }
    async function submitRework() {
      const o = reworkOrder.value
      const f = reworkForm.value
      if (!f.process_id) { showToast("请选择工序", "error"); return }
      if (!f.quantity || f.quantity < 1) { showToast("数量必须大于0", "error"); return }
      if (!f.reason.trim()) { showToast("请输入返工原因", "error"); return }
      try {
        await api.scan({ order_id: o.id, process_id: parseInt(f.process_id), quantity: parseInt(f.quantity), report_type: "rework", remark: f.reason })
        showToast("返工申请已提交")
        showReworkModal.value = false
        await load()
      } catch(e) { showToast(e.message || "提交失败", "error") }
    }

    const showReworkModal = ref(false)
    const reworkOrder = ref(null)
    const reworkForm = ref({ process_id: '', quantity: 1, reason: '' })

    // 工件进度弹窗
    const progressOrder = ref(null)
    const progressLoading = ref(false)
    const progressData = ref(null)

    const form = ref({
      order_no:'', customer:'', customer_id:null, product_name:'', product_code:'',
      quantity:1, plan_start:'', plan_end:'', deadline:'', route_id:'', remark:'', status:'pending'
    })

    // ===== 订单物料配方 =====
    const orderMaterials = ref([])
    const orderMatForm = ref({ material_id: '', quantity_per_unit: 1, process_id: null })
    const materialOptions = ref([])
    const processOptions = ref([])

    async function loadOrderMaterials(orderId) {
      try { const d = await api.listOrderMaterials(orderId); orderMaterials.value = d.materials || [] } catch(e) { orderMaterials.value = [] }
    }
    async function loadMaterialOptions() {
      try { const d = await api.listMaterials(); materialOptions.value = d.materials || [] } catch(e) {}
    }
    async function loadProcessOptions() {
      try { const d = await api.listProcesses(); processOptions.value = d.items || d.processes || []; const xl = processOptions.value.find(p => p.name === '下料'); if (xl) orderMatForm.value.process_id = xl.id; else if (processOptions.value.length > 0) orderMatForm.value.process_id = processOptions.value[0].id } catch(e) {}
    }
    async function addOrderMaterial() {
      if (!orderMatForm.value.material_id) { showToast('请选择物料', 'error'); return }
      try {
        await api.addOrderMaterial(modalId.value, {
          material_id: orderMatForm.value.material_id,
          quantity_per_unit: parseFloat(orderMatForm.value.quantity_per_unit) || 1,
          process_id: orderMatForm.value.process_id || null
        })
        orderMatForm.value = { material_id: '', quantity_per_unit: 1, process_id: null }
        showToast('物料已添加')
        await loadOrderMaterials(modalId.value)
      } catch(e) { showToast(e.message || '添加失败', 'error') }
    }
    async function removeOrderMaterial(omId) {
      try {
        await api.deleteOrderMaterial(modalId.value, omId)
        await loadOrderMaterials(modalId.value)
      } catch(e) { showToast(e.message || '删除失败', 'error') }
    }



    // ===== 产品搜索 Combobox (修复：原模板引用但组件未定义) =====
    const productSearch = ref('')
    const showProductDropdown = ref(false)
    const productSearchResults = ref([])
    const recentProducts = ref([])
    const productCursor = ref(-1)

    function onProductSearchFocus() { showProductDropdown.value = true; productCursor.value = -1 }
        let _productSearchTimer = null
    function onProductSearchInput() {
      const q = (productSearch.value || '').trim().toLowerCase()
      if (!q) { productSearchResults.value = []; productCursor.value = -1; return }
      clearTimeout(_productSearchTimer)
      _productSearchTimer = setTimeout(() => {
        productSearchResults.value = products.value.filter(p =>
          (p.product_code || '').toLowerCase().includes(q) ||
          (p.product_name || '').toLowerCase().includes(q)
        )
        productCursor.value = productSearchResults.value.length ? 0 : -1
      }, 250)
    }
    function moveProductCursor(dir) {
      const list = productSearch.value ? productSearchResults.value : recentProducts.value
      if (!list.length) return
      productCursor.value = Math.min(Math.max(productCursor.value + dir, 0), list.length - 1)
    }
    function selectProductByEnter() {
      const list = productSearch.value ? productSearchResults.value : recentProducts.value
      if (productCursor.value >= 0 && productCursor.value < list.length) {
        selectProduct(list[productCursor.value])
      }
    }
    function clearProductSearch() {
      productSearch.value = ''
      productSearchResults.value = []
      productCursor.value = -1
    }
    function selectProduct(p) {
      form.value.product_code = p.product_code || ''
      form.value.product_name = p.product_name || ''
      form.value.model = p.model || ''
      form.value.spec = p.spec || ''
      form.value.style = p.style || ''
      form.value.upper_opening = p.upper_opening || ''
      form.value.plate_thickness = p.plate_thickness || ''
      form.value.category = p.category || ''
      form.value.route_id = p.route_id || ''
      if (p.price) form.value.price = p.price
      if (p.weight) form.value.weight = p.weight
      productSearch.value = p.product_code || ''
      showProductDropdown.value = false
      productCursor.value = -1
      // 记录最近使用
      const existing = recentProducts.value.findIndex(r => r.id === p.id)
      if (existing >= 0) recentProducts.value.splice(existing, 1)
      recentProducts.value.unshift(p)
      if (recentProducts.value.length > 5) recentProducts.value.pop()
    }

    const statusMap = {
      'pending':   { label:'待生产', cls:'badge-pending' },
      'producing': { label:'生产中', cls:'badge-warning' },
      'completed': { label:'已完成', cls:'badge-success' },
      'cancelled': { label:'已取消', cls:'badge-danger' },
      'paused':    { label:'已暂停', cls:'badge-secondary' },
    }

    // 统计 — 使用后端返回的全局计数，而非当前分页的 filtered 计数
    const pendingCount   = ref(0)
    const producingCount = ref(0)
    const completedCount = ref(0)

    // 权限
    const canCreate = computed(() => can('orders:create'))
    const canEdit   = computed(() => can('orders:edit'))
    const canDelete = computed(() => can('orders:delete'))
    const canView   = computed(() => can('orders:view'))

    // 进度百分比
    function pct(o) {
      const done = (o.completed || 0) + (o.scrapped || 0)
      if (!o.quantity) return 0
      return Math.min(100, Math.round(done / o.quantity * 100))
    }
    function scrapPct(o) {
      if (!o.quantity || !o.scrapped) return 0
      return Math.round(o.scrapped / o.quantity * 100)
    }
    function isOverdue(o) {
      if (!o.plan_end) return false;
      const today = new Date(); today.setHours(0,0,0,0);
      const planEnd = new Date(o.plan_end);
      return planEnd < today && o.status !== 'completed';
    }

    // ===== 附件管理 =====
    const attachments = ref({})       // { order_id: [...] }
    const attachmentsLoading = ref({}) // { order_id: true/false }
    const uploadInputRef = ref(null)

    async function loadAttachments(orderId) {
      attachmentsLoading.value = { ...attachmentsLoading.value, [orderId]: true }
      try {
        const d = await api.listOrderAttachments(orderId)
        attachments.value = { ...attachments.value, [orderId]: d.attachments || [] }
      } catch(e) {
        showToast('加载附件失败: ' + (e.message || ''), 'error')
      } finally {
        attachmentsLoading.value = { ...attachmentsLoading.value, [orderId]: false }
      }
    }

    function getAttachments(orderId) {
      return attachments.value[orderId] || []
    }

    function isAttachmentsLoading(orderId) {
      return !!attachmentsLoading.value[orderId]
    }

    async function handleAttachmentUpload(orderId, event) {
      const file = event.target.files?.[0]
      if (!file) return
      const formData = new FormData()
      formData.append('file', file)
      try {
        await api.uploadOrderAttachment(orderId, formData)
        showToast('上传成功')
        await loadAttachments(orderId)
      } catch(e) {
        showToast('上传失败: ' + (e.message || ''), 'error')
      } finally {
        event.target.value = ''
      }
    }

    async function delAttachment(attachmentId, orderId) {
      if (!confirm('确定删除此附件吗？')) return
      try {
        await api.deleteAttachment(attachmentId)
        showToast('删除成功')
        await loadAttachments(orderId)
      } catch(e) {
        showToast('删除失败: ' + (e.message || ''), 'error')
      }
    }

    function downloadAttachment(attachmentId) {
      // httpOnly cookie handles auth automatically
      window.open('/api/attachments/' + attachmentId + '/download', '_blank')
    }

    function getFileIcon(fileType) {
      if (!fileType) return '📎'
      const t = fileType.toLowerCase()
      if (t.includes('image')) return '🖼️'
      if (t.includes('pdf')) return '📄'
      if (t.includes('word') || t.includes('document')) return '📝'
      if (t.includes('spreadsheet') || t.includes('excel')) return '📊'
      if (t.includes('cad') || t.includes('dwg') || t.includes('dxf')) return '📐'
      if (t.includes('zip') || t.includes('rar') || t.includes('compress')) return '📦'
      return '📎'
    }

    function formatFileSize(bytes) {
      if (!bytes) return '0 B'
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    }

    // 详情展开时自动加载附件
    function toggleExpandAndLoad(id) {
      toggleExpand(id)
      if (expandedId.value === id && !attachments.value[id]) {
        loadAttachments(id)
      }
    }

    // ===== 数据加载 =====
    async function load() {
      loading.value = true
      try {
        const params = { page: page.value, limit: limit.value }
        if (filterStatus.value) params.status = filterStatus.value
        if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
        if (filterCustomer.value.trim()) params.customer = filterCustomer.value.trim()
        const d = await api.listOrders(params)
        orders.value = d.orders || []
        total.value = d.total || 0
        pendingCount.value   = d.pending ?? 0
        producingCount.value = d.producing ?? 0
        completedCount.value = d.completed ?? 0
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }


    let _searchTimer = null
    function searchAndLoad() { page.value = 1; load() }
    function debouncedSearch() {
      if (_searchTimer) clearTimeout(_searchTimer)
      _searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
    }
    function customerChange() { page.value = 1; load() }

    async function loadDropdownData() {
      try { const d = await api.listProductionLines(); productionLines.value = d.lines || [] } catch(e) { productionLines.value = [] }
      try {
        const [custData, prodData, routeData] = await Promise.all([
          api.listCustomers(),
          api.listProducts(),
          api.listProcessRoutes()
        ])
        customers.value = custData.customers || []
        products.value = prodData.products || []
        processRoutes.value = routeData.routes || []
      } catch(e) { /* silent */ }
    }

    // ===== 联动逻辑 =====
    function onCustomerChange() {
      const id = form.value.customer_id
      if (!id) { form.value.customer = ''; return }
      const found = customers.value.find(c => c.id === parseInt(id) || c.id == id)
      form.value.customer = found ? found.name : ''
    }
    function toggleExpand(id) { expandedId.value = expandedId.value === id ? null : id }

    // ===== 模态框操作 =====
    async function openAdd() {
      form.value = {
        order_no:'', customer:'', customer_id:null, product_name:'', product_code:'',
        model:'', spec:'', style:'', upper_opening:'', plate_thickness:'', category:'',
        quantity:1, plan_start:'', plan_end:'', deadline:'', route_id:'', production_line_id:null, remark:'', status:'pending'
      }
      productSearch.value = ''
      showProductDropdown.value = false
      productSearchResults.value = []
      modalEdit.value = false; modalId.value = null
      loadDropdownData()
      try { const d = await api.nextOrderNo(); form.value.order_no = d.order_no } catch(e) { showToast('自动生成订单号失败：' + (e.message || '请手动输入'), 'warn') }
      showModal.value = true
    }

    function openEdit(o) {
      form.value = {
        order_no: o.order_no || '',
        customer: o.customer || '',
        customer_id: o.customer_id || null,
        product_name: o.product_name || '',
        product_code: o.product_code || '',
        quantity: o.quantity || 1,
        plan_start: o.plan_start || '',
        plan_end: o.plan_end || '',
        deadline: o.deadline || '',
        route_id: o.route_id || '',
        production_line_id: o.production_line_id || null,
        remark: o.remark || '',
        status: o.status || 'pending'
      }
      productSearch.value = o.product_code || ''
      modalEdit.value = true; modalId.value = o.id
      loadDropdownData()
      loadMaterialOptions()
      loadProcessOptions()
      loadOrderMaterials(o.id)
      // Get product weight from loaded products list
      const product = products.value.find(p => p.product_code === o.product_code)
      orderMatForm.value.quantity_per_unit = parseFloat(product?.weight) || parseFloat(o.weight) || parseFloat(o.product_weight) || 1
      orderMatForm.value.process_id = processOptions.value[0]?.id || null
      showModal.value = true
    }

    async function save() {
      if (!form.value.order_no) { showToast('请输入订单号','error'); return }
      if (!(form.value.product_name || '').trim()) { showToast('请输入产品名称','error'); return }
      if (!form.value.quantity || form.value.quantity < 1) { showToast('请输入有效数量','error'); return }
      try {
        const data = { ...form.value }
        data.quantity = parseInt(data.quantity)
        if (data.route_id) data.route_id = parseInt(data.route_id) || null
        else delete data.route_id
        if (data.customer_id) data.customer_id = parseInt(data.customer_id)
        if (data.production_line_id) data.production_line_id = parseInt(data.production_line_id) || null
        else data.production_line_id = null

        if (modalEdit.value) {
          await api.updateOrder(modalId.value, data)
          showToast('更新成功')
        } else {
          await api.createOrder(data)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }

    async function del(o) {
      if (!confirm('确定将订单 ' + o.order_no + ' 移入回收站吗？\n30天后可从回收站彻底删除。')) return
      try { await api.deleteOrder(o.id); showToast('已移至回收站'); await load() } catch(e) { showToast(e.message || '删除失败', 'error') }
    }

    // ===== 回收站 =====
    const showTrash = ref(false)
    const trashOrders = ref([])
    const trashTotal = ref(0)
    const trashPage = ref(1)
    const trashPageSize = 20

    async function loadTrash() {
      try {
        const d = await api.trashOrders({ page: trashPage.value, limit: trashPageSize })
        trashOrders.value = d.orders || []
        trashTotal.value = d.total || 0
      } catch(e) { showToast(e.message || '加载失败', 'error') }
    }

    async function restoreOrder(oid) {
      try { await api.restoreOrder(oid); showToast('订单已恢复'); await loadTrash(); await load() } catch(e) { showToast(e.message || '恢复失败', 'error') }
    }

    async function permanentDelete(oid) {
      if (!confirm('确认彻底删除该订单？所有关联数据将永久消失，不可恢复！')) return
      try {
        // 彻底删除：需要调用后端硬删除接口
        await api.purgeOrder(oid)
        showToast('已彻底删除')
        await loadTrash()
      } catch(e) { showToast(e.message || '删除失败', 'error') }
    }

    // ===== 工件进度看板 =====
    async function openProgress(o) {
      progressOrder.value = o
      progressLoading.value = true
      progressData.value = null
      try {
        const d = await api.getWorkpieceProgress(o.id)
        progressData.value = d
      } catch(e) {
        showToast('加载进度失败: ' + (e.message || ''), 'error')
        progressOrder.value = null
      } finally {
        progressLoading.value = false
      }
    }


    function prevPage() { if (page.value > 1) { page.value--; load() } }
    function nextPage() { if (page.value * limit.value < total.value) { page.value++; load() } }

    onMounted(async () => { await loadDropdownData(); load() })

    return {
      orders, loading, total, page, limit, filterStatus, searchKeyword, filterCustomer,
      expandedId, toggleExpand, toggleExpandAndLoad, pct, scrapPct, isOverdue, statusMap,
      pendingCount, producingCount, completedCount,
      // 下拉数据
      customers, products, processRoutes, productionLines,
      // 联动
      onCustomerChange,
      // 模态框
      showModal, modalEdit, form,
      openAdd, openEdit, save, del, prevPage, nextPage, load, searchAndLoad, debouncedSearch, customerChange, auth,
      // 产品搜索 Combobox (修复)
      productSearch, showProductDropdown, productSearchResults, recentProducts, productCursor,
      onProductSearchFocus, onProductSearchInput, moveProductCursor, selectProductByEnter,
      clearProductSearch, selectProduct,
      // 二维码打印 (from useQrcode)
      ...qr,
      // 附件管理
      getAttachments, isAttachmentsLoading, handleAttachmentUpload, delAttachment, downloadAttachment, getFileIcon, formatFileSize,
      // 回收站
      canCreate, canEdit, canDelete, canView,
      showTrash, trashOrders, trashTotal, trashPage, trashPageSize, loadTrash, restoreOrder, permanentDelete,
      // 工件进度看板
      progressOrder, progressLoading, progressData, openProgress,
      // 订单物料配方
      orderMaterials, orderMatForm, materialOptions, processOptions,
      loadOrderMaterials, addOrderMaterial, removeOrderMaterial, loadMaterialOptions, loadProcessOptions,
      // 申请返工
      showReworkModal, reworkOrder, reworkForm, openRework, submitRework
    }
}
