// OrderList Composable
import { ref, onMounted, watch, nextTick, computed } from '../vendor/vue.esm.js'
import { api } from '../api.js?v=60'
import { showToast } from '../store.js?v=60'
import { handleApiError } from '../api.js'
import { auth, can } from '../auth.js'

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

    // 详情展开
    const expandedId = ref(null)

    // 模态框
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)

    // 二维码打印
    const showQrPrint = ref(false)
    const qrPrintOrder = ref(null)
    const qrMode = ref('order')
    const qrCodes = ref([])
    const qrPrintLoading = ref(false)
    const qrPrintCopies = ref(1)
    const qrPrintSize = ref('small')

    // 工件进度弹窗
    const progressOrder = ref(null)
    const progressLoading = ref(false)
    const progressData = ref(null)

    const form = ref({
      order_no:'', customer:'', customer_id:null, product_name:'', product_code:'',
      quantity:1, plan_start:'', plan_end:'', deadline:'', route_id:'', remark:'', status:'pending'
    })



    // ===== 产品搜索 Combobox (修复：原模板引用但组件未定义) =====
    const productSearch = ref('')
    const showProductDropdown = ref(false)
    const productSearchResults = ref([])
    const recentProducts = ref([])
    const productCursor = ref(-1)

    function onProductSearchFocus() { showProductDropdown.value = true; productCursor.value = -1 }
        let _searchTimer = null
    function onProductSearchInput() {
      const q = (productSearch.value || '').trim().toLowerCase()
      if (!q) { productSearchResults.value = []; productCursor.value = -1; return }
      clearTimeout(_searchTimer)
      _searchTimer = setTimeout(() => {
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

    async function loadDropdownData() {
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
        quantity:1, plan_start:'', plan_end:'', deadline:'', route_id:'', remark:'', status:'pending'
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
        remark: o.remark || '',
        status: o.status || 'pending'
      }
      productSearch.value = o.product_code || ''
      modalEdit.value = true; modalId.value = o.id
      loadDropdownData()
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
        await api.delete(`/api/orders/${oid}/purge`)
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
        const d = await api.get('/api/orders/' + o.id + '/workpiece-progress')
        progressData.value = d
      } catch(e) {
        showToast('加载进度失败: ' + (e.message || ''), 'error')
        progressOrder.value = null
      } finally {
        progressLoading.value = false
      }
    }

    // ===== 二维码打印 =====
    function openQrPrint(o) {
      qrPrintOrder.value = o
      qrMode.value = 'order'
      qrCodes.value = []
      showQrPrint.value = true
    }

    async function generateQrCodes() {
      if (!qrPrintOrder.value) return
      qrPrintLoading.value = true
      qrCodes.value = []
      try {
        const d = await api.post('/api/qrcode/batch', {
          order_ids: [qrPrintOrder.value.id],
          mode: qrMode.value
        })
        qrCodes.value = d.codes || []
        if (!qrCodes.value.length) {
          showToast('未生成二维码', 'warn')
        } else {
          const modeText = qrMode.value === 'serial' ? '序列号模式' : '订单模式'
          showToast(`已生成 ${qrCodes.value.length} 个二维码 (${modeText})`)
        }
      } catch(e) {
        showToast('二维码生成失败: ' + (e.message || '未知错误'), 'error')
      } finally {
        qrPrintLoading.value = false
      }
    }

    function switchQrMode(mode) {
      qrMode.value = mode
      qrCodes.value = []
    }

    function escapeHtml(text) {
      if (!text) return ''
      const div = document.createElement('div')
      div.appendChild(document.createTextNode(text))
      return div.innerHTML
    }

    function printQrCodes() {
      if (!qrCodes.value.length) { showToast('请先生成二维码', 'warn'); return }
      const root = document.getElementById('qr-print-root')
      if (!root) { showToast('打印容器未找到', 'error'); return }
      let html = '<div class="qr-print-grid">'
      for (let copy = 0; copy < qrPrintCopies.value; copy++) {
        for (const code of qrCodes.value) {
          html += '<div class="qr-card">'
          html += '<img src="' + code.qrcode + '" alt="' + (code.serial_no || code.order_no) + '">'
          html += '<div class="qr-label-info">'
          html += '<div class="qr-label-no">' + escapeHtml(code.serial_no || code.order_no) + '</div>'
          if (code.product_code) {
            html += '<div class="qr-label-code">' + escapeHtml(code.product_code) + '</div>'
          }
          html += '</div></div>'
        }
      }
      html += '</div>'
      root.innerHTML = html
      setTimeout(() => { window.print() }, 100)
    }

    function prevPage() { if (page.value > 1) { page.value--; load() } }
    function nextPage() { if (page.value * limit.value < total.value) { page.value++; load() } }

    watch(filterStatus, () => { page.value = 1; load() })

    // 搜索输入变更时重置页码
    let searchTimer = null
    function debouncedSearch() {
      clearTimeout(searchTimer)
      searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
    }
    function searchAndLoad() { clearTimeout(searchTimer); page.value = 1; load() }
    function customerChange() { page.value = 1; load() }

    onMounted(async () => { await loadDropdownData(); load() })

    return {
      orders, loading, total, page, limit, filterStatus, searchKeyword, filterCustomer,
      expandedId, toggleExpand, toggleExpandAndLoad, pct, scrapPct, isOverdue, statusMap,
      pendingCount, producingCount, completedCount,
      // 下拉数据
      customers, products, processRoutes,
      // 联动
      onCustomerChange,
      // 模态框
      showModal, modalEdit, form,
      openAdd, openEdit, save, del, prevPage, nextPage, load, searchAndLoad, debouncedSearch, customerChange, auth,
      // 产品搜索 Combobox (修复)
      productSearch, showProductDropdown, productSearchResults, recentProducts, productCursor,
      onProductSearchFocus, onProductSearchInput, moveProductCursor, selectProductByEnter,
      clearProductSearch, selectProduct,
      // 二维码打印
      showQrPrint, qrPrintOrder, qrMode, qrCodes, qrPrintLoading,
      qrPrintCopies, qrPrintSize,
      openQrPrint, generateQrCodes, switchQrMode, printQrCodes,
      // 附件管理
      getAttachments, isAttachmentsLoading, handleAttachmentUpload, delAttachment, downloadAttachment, getFileIcon, formatFileSize,
      // 回收站
      canCreate, canEdit, canDelete, canView,
      showTrash, trashOrders, trashTotal, trashPage, trashPageSize, loadTrash, restoreOrder, permanentDelete,
      // 工件进度看板
      progressOrder, progressLoading, progressData, openProgress
    }
}
