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
    const archiveFilter = ref('active')
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
    function isCompletedOrder(o) {
      return (o?.status || '') === 'completed'
    }
    function completedReadonlyToast() {
      showToast('已完成订单已归档，只读，请先重新打开订单', 'error')
    }
    function openRework(o) {
      if (isCompletedOrder(o)) { completedReadonlyToast(); return }
      reworkOrder.value = o
      reworkForm.value = { process_id: "", quantity: 1, reason: "" }
      showReworkModal.value = true
    }
    async function submitRework() {
      const o = reworkOrder.value
      const f = reworkForm.value
      if (!f.process_id) { showToast("请选择工序", "error"); return }
      if (!f.quantity || f.quantity < 1) { showToast("数量必须大于0", "error"); return }
      if (!f.reason.trim()) { showToast("请输入返工原因", "error"); return }
      try {
        await api.domains.scan.scan({ order_id: o.id, process_id: parseInt(f.process_id), quantity: parseInt(f.quantity), report_type: "rework", remark: f.reason })
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
    const showCompletionFocus = ref(false)
    const completionFocusLoading = ref(false)
    const completionFocusData = ref({ summary: {}, items: [] })
    const completionFocusConfig = ref({ mode: 'soft', tail_percent: 70, reason_options: [], mode_options: [] })
    const showFocusExceptionModal = ref(false)
    const focusExceptionOrder = ref(null)
    const focusExceptionForm = ref({ reason: '缺料', detail: '', expires_at: '' })

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
      try { const d = await api.domains.products.listOrderMaterials(orderId); orderMaterials.value = d.materials || [] } catch(e) { orderMaterials.value = [] }
    }
    async function loadMaterialOptions() {
      try {
        const d = await api.domains.materials.listMaterials()
        materialOptions.value = d.materials || []
      } catch(e) {
        materialOptions.value = []
        showToast(e.message || '加载物料选项失败', 'error')
      }
    }
    async function loadProcessOptions() {
      try {
        const d = await api.domains.processes.listProcesses()
        processOptions.value = d.items || d.processes || []
        const xl = processOptions.value.find(p => p.name === '下料')
        if (xl) orderMatForm.value.process_id = xl.id
        else if (processOptions.value.length > 0) orderMatForm.value.process_id = processOptions.value[0].id
      } catch(e) {
        processOptions.value = []
        showToast(e.message || '加载工序选项失败', 'error')
      }
    }
    async function addOrderMaterial() {
      if (!orderMatForm.value.material_id) { showToast('请选择物料', 'error'); return }
      try {
        await api.domains.products.addOrderMaterial(modalId.value, {
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
        await api.domains.products.deleteOrderMaterial(modalId.value, omId)
        await loadOrderMaterials(modalId.value)
      } catch(e) { showToast(e.message || '删除失败', 'error') }
    }



    // ===== 产品搜索 Combobox (修复：原模板引用但组件未定义) =====
    const productSearch = ref('')
    const showProductDropdown = ref(false)
    const productSearchResults = ref([])
    const recentProducts = ref([])
    const productCursor = ref(-1)
    // ===== 工序路线搜索 Combobox =====
    const routeSearch = ref('')
    const showRouteDropdown = ref(false)
    const routeCursor = ref(-1)

    const filteredRoutes = computed(() => {
      const q = (routeSearch.value || '').trim().toLowerCase()
      if (!q) return processRoutes.value
      return processRoutes.value.filter(r =>
        (r.name || '').toLowerCase().includes(q)
      )
    })

    function onRouteSearchFocus() { showRouteDropdown.value = true; routeCursor.value = -1 }
    function onRouteSearchInput() { routeCursor.value = filteredRoutes.value.length ? 0 : -1 }
    function moveRouteCursor(dir) {
      const list = filteredRoutes.value
      if (!list.length) return
      routeCursor.value = Math.min(Math.max(routeCursor.value + dir, 0), list.length - 1)
    }
    function selectRouteByEnter() {
      const list = filteredRoutes.value
      if (routeCursor.value >= 0 && routeCursor.value < list.length) {
        selectRoute(list[routeCursor.value])
      }
    }
    function clearRouteSearch() {
      routeSearch.value = ''
      routeCursor.value = -1
      form.value.route_id = ''
    }
    function selectRoute(r) {
      form.value.route_id = r.id
      routeSearch.value = r.name || ''
      showRouteDropdown.value = false
      routeCursor.value = -1
    }

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
    function riskLabel(level) {
      return ({
        none: '无风险',
        low: '低',
        medium: '中',
        high: '高',
        overdue: '已延期'
      })[level] || '低'
    }
    function formatHours(value) {
      if (value === null || value === undefined || value === '') return '-'
      const hours = Number(value)
      if (!Number.isFinite(hours)) return '-'
      if (hours < 24) return `${hours.toFixed(1)} 小时`
      return `${(hours / 24).toFixed(1)} 天`
    }
    function completionFocusModeOptions() {
      const options = completionFocusConfig.value.mode_options || []
      if (options.length) return options
      return [
        { value: 'off', label: '\u5173\u95ed', button_class: 'btn-primary' },
        { value: 'soft', label: '\u8f6f\u63d0\u793a', button_class: 'btn-warning' },
        { value: 'hard', label: '\u5f3a\u62e6\u622a', button_class: 'btn-danger' },
      ]
    }
    function completionFocusModeLabel(mode) {
      const option = completionFocusModeOptions().find(item => item.value === mode)
      return option ? option.label : (mode || '')
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
        const d = await api.domains.orderAttachments.listOrderAttachments(orderId)
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
      const order = orders.value.find(item => item.id === orderId)
      if (isCompletedOrder(order)) {
        completedReadonlyToast()
        event.target.value = ''
        return
      }
      const file = event.target.files?.[0]
      if (!file) return
      const formData = new FormData()
      formData.append('file', file)
      try {
        await api.domains.orderAttachments.uploadOrderAttachment(orderId, formData)
        showToast('上传成功')
        await loadAttachments(orderId)
      } catch(e) {
        showToast('上传失败: ' + (e.message || ''), 'error')
      } finally {
        event.target.value = ''
      }
    }

    async function delAttachment(attachmentId, orderId) {
      const order = orders.value.find(item => item.id === orderId)
      if (isCompletedOrder(order)) { completedReadonlyToast(); return }
      if (!confirm('确定删除此附件吗？')) return
      try {
        await api.domains.orderAttachments.deleteAttachment(attachmentId)
        showToast('删除成功')
        await loadAttachments(orderId)
      } catch(e) {
        showToast('删除失败: ' + (e.message || ''), 'error')
      }
    }

    function downloadAttachment(attachmentId) {
      // httpOnly cookie handles auth automatically
      window.open(api.domains.orderAttachments.downloadAttachment(attachmentId), '_blank')
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
        const params = { page: page.value, limit: limit.value, archive: archiveFilter.value }
        if (filterStatus.value) params.status = filterStatus.value
        if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
        if (filterCustomer.value.trim()) params.customer = filterCustomer.value.trim()
        const d = await api.domains.orders.listOrders(params)
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
    function archiveChange() { page.value = 1; load() }
    function statusChange() { page.value = 1; load() }
    function debouncedSearch() {
      if (_searchTimer) clearTimeout(_searchTimer)
      _searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
    }
    function customerChange() { page.value = 1; load() }

    async function loadDropdownData() {
      try { const d = await api.domains.production.listProductionLines(); productionLines.value = d.lines || [] } catch(e) { productionLines.value = [] }
      try {
        const [custData, prodData, routeData] = await Promise.all([
          api.domains.customers.listCustomers(),
          api.domains.products.listProducts(),
          api.domains.processRoutes.listProcessRoutes()
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
      try { const d = await api.domains.orders.nextOrderNo(); form.value.order_no = d.order_no } catch(e) { showToast('自动生成订单号失败：' + (e.message || '请手动输入'), 'warn') }
      showModal.value = true
    }

    function openEdit(o) {
      if (isCompletedOrder(o)) { completedReadonlyToast(); return }
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
          await api.domains.orders.updateOrder(modalId.value, data)
          showToast('更新成功')
        } else {
          await api.domains.orders.createOrder(data)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }

    async function del(o) {
      if (isCompletedOrder(o)) { completedReadonlyToast(); return }
      if (!confirm('确定将订单 ' + o.order_no + ' 移入回收站吗？\n30天后可从回收站彻底删除。')) return
      try { await api.domains.orders.deleteOrder(o.id); showToast('已移至回收站'); await load() } catch(e) { showToast(e.message || '删除失败', 'error') }
    }

    async function reopenOrder(o) {
      const reason = window.prompt('请输入重新打开订单的原因：', '')
      if (reason === null) return
      if (!reason.trim()) { showToast('请填写重新打开原因', 'error'); return }
      try {
        await api.domains.orders.reopenOrder(o.id, { reason: reason.trim(), status: 'producing' })
        showToast('订单已重新打开')
        await load()
      } catch(e) {
        showToast(e.message || '重新打开失败', 'error')
      }
    }

    // ===== 回收站 =====
    const showTrash = ref(false)
    const trashOrders = ref([])
    const trashTotal = ref(0)
    const trashPage = ref(1)
    const trashPageSize = 20

    async function loadTrash() {
      try {
        const d = await api.domains.orders.trashOrders({ page: trashPage.value, limit: trashPageSize })
        trashOrders.value = d.orders || []
        trashTotal.value = d.total || 0
      } catch(e) { showToast(e.message || '加载失败', 'error') }
    }

    async function restoreOrder(oid) {
      try { await api.domains.orders.restoreOrder(oid); showToast('订单已恢复'); await loadTrash(); await load() } catch(e) { showToast(e.message || '恢复失败', 'error') }
    }

    async function permanentDelete(oid) {
      if (!confirm('确认彻底删除该订单？所有关联数据将永久消失，不可恢复！')) return
      try {
        // 彻底删除：需要调用后端硬删除接口
        await api.domains.orders.purgeOrder(oid)
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
        const d = await api.domains.orders.getWorkpieceProgress(o.id)
        progressData.value = d
      } catch(e) {
        showToast('加载进度失败: ' + (e.message || ''), 'error')
        progressOrder.value = null
      } finally {
        progressLoading.value = false
      }
    }

    async function openCompletionFocus() {
      showCompletionFocus.value = true
      completionFocusLoading.value = true
      try {
        try {
          completionFocusConfig.value = await api.domains.orders.getCompletionFocusConfig()
        } catch(e) {}
        completionFocusData.value = await api.domains.orders.getCompletionFocus({ limit: 120 })
        if (completionFocusData.value.config) completionFocusConfig.value = completionFocusData.value.config
      } catch(e) {
        completionFocusData.value = { summary: {}, items: [] }
        showToast(e.message || '加载集中完工看板失败', 'error')
      } finally {
        completionFocusLoading.value = false
      }
    }

    async function setCompletionFocusMode(mode) {
      try {
        const res = await api.domains.orders.saveCompletionFocusConfig({
          mode,
          tail_percent: completionFocusConfig.value.tail_percent || 70
        })
        completionFocusConfig.value = res.config || { ...completionFocusConfig.value, mode }
        showToast('集中完工模式已切换为：' + completionFocusModeLabel(mode))
        await openCompletionFocus()
      } catch(e) {
        showToast(e.message || '保存集中完工模式失败', 'error')
      }
    }

    function openFocusException(item) {
      focusExceptionOrder.value = item
      const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000)
      tomorrow.setMinutes(tomorrow.getMinutes() - tomorrow.getTimezoneOffset())
      focusExceptionForm.value = {
        reason: (completionFocusConfig.value.reason_options || ['缺料'])[0] || '缺料',
        detail: '',
        expires_at: tomorrow.toISOString().slice(0, 16)
      }
      showFocusExceptionModal.value = true
    }

    async function saveFocusException() {
      const order = focusExceptionOrder.value
      if (!order) return
      if (!focusExceptionForm.value.reason) { showToast('请选择例外原因', 'error'); return }
      try {
        await api.domains.orders.createCompletionFocusException(order.order_id, {
          ...focusExceptionForm.value,
          expires_at: (focusExceptionForm.value.expires_at || '').replace('T', ' ')
        })
        showToast('已设置例外订单')
        showFocusExceptionModal.value = false
        await openCompletionFocus()
      } catch(e) {
        showToast(e.message || '设置例外失败', 'error')
      }
    }

    async function cancelFocusException(item) {
      const id = item?.exception?.id
      if (!id) return
      if (!confirm('确认取消该订单的集中完工例外？')) return
      try {
        await api.domains.orders.cancelCompletionFocusException(id, { reason: '手动取消' })
        showToast('已取消例外')
        await openCompletionFocus()
      } catch(e) {
        showToast(e.message || '取消例外失败', 'error')
      }
    }


    function prevPage() { if (page.value > 1) { page.value--; load() } }
    function nextPage() { if (page.value * limit.value < total.value) { page.value++; load() } }

    onMounted(async () => { await loadDropdownData(); load() })

    return {
      orders, loading, total, page, limit, filterStatus, archiveFilter, searchKeyword, filterCustomer,
      expandedId, toggleExpand, toggleExpandAndLoad, pct, scrapPct, isOverdue, statusMap,
      pendingCount, producingCount, completedCount,
      riskLabel, formatHours,
      // 下拉数据
      customers, products, processRoutes, productionLines,
      // 工序路线搜索 Combobox
      routeSearch, showRouteDropdown, routeCursor, filteredRoutes,
      onRouteSearchFocus, onRouteSearchInput, moveRouteCursor, selectRouteByEnter,
      clearRouteSearch, selectRoute,
      // 联动
      onCustomerChange,
      // 模态框
      showModal, modalEdit, form,
      openAdd, openEdit, save, del, reopenOrder, prevPage, nextPage, load, searchAndLoad,
      debouncedSearch, archiveChange, statusChange, customerChange, auth,
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
      showCompletionFocus, completionFocusLoading, completionFocusData, completionFocusConfig,
      showFocusExceptionModal, focusExceptionOrder, focusExceptionForm,
      openCompletionFocus, setCompletionFocusMode, completionFocusModeOptions, completionFocusModeLabel,
      openFocusException, saveFocusException, cancelFocusException,
      // 订单物料配方
      orderMaterials, orderMatForm, materialOptions, processOptions,
      loadOrderMaterials, addOrderMaterial, removeOrderMaterial, loadMaterialOptions, loadProcessOptions,
      // 申请返工
      showReworkModal, reworkOrder, reworkForm, openRework, submitRework, isCompletedOrder
    }
}
