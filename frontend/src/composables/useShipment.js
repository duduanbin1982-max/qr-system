import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

function createEmptyForm() {
  return {
    shipment_no: '',
    customer: '',
    contact_person: '',
    contact_phone: '',
    address: '',
    remark: '',
    status: 'pending',
    material_bill_no: '',
    receivable_amount: 0,
  }
}

function createEmptyItem() {
  return {
    inventory_id: '',
    product_model: '',
    product_name: '',
    quantity: 1,
    unit: '件',
    remark: '',
    _search: '',
    _showDrop: false,
  }
}

export function useShipment() {
  const shipments = ref([])
  const loading = ref(true)
  const saving = ref(false)
  const total = ref(0)
  const page = ref(1)
  const limit = ref(20)
  const filterStatus = ref('')
  const searchKeyword = ref('')

  const inventory = ref([])

  const showModal = ref(false)
  const modalEdit = ref(false)
  const modalId = ref(null)
  const form = ref(createEmptyForm())
  const items = ref([])

  const detailShipment = ref(null)
  const showDetail = ref(false)

  const showPayModal = ref(false)
  const payTarget = ref(null)
  const payAmount = ref(0)
  const payMethod = ref('')
  const payDate = ref(new Date().toISOString().slice(0, 10))
  const payRemark = ref('')

  const statusMap = {
    pending: { label: '待出库', cls: 'badge-info' },
    completed: { label: '已出库', cls: 'badge-success' },
    received: { label: '已签收', cls: 'badge-primary' },
  }
  const paymentStatusMap = {
    unpaid: { label: '未收款', cls: 'badge-info' },
    partial: { label: '部分收', cls: 'badge-warning' },
    paid: { label: '已收清', cls: 'badge-success' },
  }

  const pendingCount = ref(0)
  const completedCount = ref(0)
  const receivableTotal = computed(() => shipments.value.reduce((sum, row) => sum + (row.receivable_amount || 0), 0))
  const paidTotal = computed(() => shipments.value.reduce((sum, row) => sum + (row.paid_amount || 0), 0))
  const unpaidTotal = computed(() => receivableTotal.value - paidTotal.value)

  const canCreate = computed(() => can('shipments:create'))
  const canEdit = computed(() => can('shipments:edit'))
  const canDelete = computed(() => can('shipments:delete'))

  async function load() {
    loading.value = true
    try {
      const params = { page: page.value, limit: limit.value }
      if (filterStatus.value) params.status = filterStatus.value
      if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
      const data = await api.listShipments(params)
      shipments.value = data.shipments || []
      total.value = data.total || 0
      pendingCount.value = data.pending_count ?? 0
      completedCount.value = data.completed_count ?? 0
    } catch (error) {
      showToast(error.message || '加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  async function loadInventory() {
    try {
      const data = await api.listInventory()
      inventory.value = data.items || []
    } catch (error) {
      showToast('加载库存列表失败', 'warn')
    }
  }

  async function openAdd() {
    form.value = createEmptyForm()
    items.value = []
    modalEdit.value = false
    modalId.value = null
    try {
      const data = await api.draftShipment()
      form.value.shipment_no = data.shipment_no
    } catch (error) {
      showToast('自动生成出库单号失败，请手动输入', 'warn')
    }
    showModal.value = true
  }

  function openEdit(shipment) {
    form.value = {
      shipment_no: shipment.shipment_no,
      material_bill_no: shipment.material_bill_no || '',
      customer: shipment.customer || '',
      contact_person: shipment.contact_person || '',
      contact_phone: shipment.contact_phone || '',
      address: shipment.address || '',
      remark: shipment.remark || '',
      status: shipment.status || 'pending',
      receivable_amount: shipment.receivable_amount || 0,
    }
    items.value = []
    modalEdit.value = true
    modalId.value = shipment.id
    showModal.value = true
  }

  function addItem() {
    items.value.push(createEmptyItem())
  }

  function resetItem(index) {
    if (!items.value[index]) return
    items.value[index] = createEmptyItem()
    updateReceivable()
  }

  function removeItem(index) {
    items.value.splice(index, 1)
    updateReceivable()
  }

  function focusItem(index) {
    if (items.value[index]) {
      items.value[index]._showDrop = true
    }
  }

  function blurItem(index) {
    setTimeout(() => {
      if (items.value[index]) {
        items.value[index]._showDrop = false
      }
    }, 150)
  }

  function updateItemSearch(index, value) {
    if (!items.value[index]) return
    items.value[index]._search = value
    items.value[index]._showDrop = true
  }

  function updateItemQuantity(index, value) {
    if (!items.value[index]) return
    items.value[index].quantity = Number(value) || 0
    updateReceivable()
  }

  function selectInventory(index, inventoryItem) {
    const current = items.value[index]
    if (!current) return
    current.inventory_id = inventoryItem.id
    current.product_model = inventoryItem.product_model
    current.product_name = inventoryItem.product_name || ''
    current.unit = inventoryItem.unit || '件'
    current._showDrop = false
    current._search = ''
    updateReceivable()
  }

  function updateReceivable() {
    let totalAmount = 0
    items.value.forEach((item) => {
      const inventoryItem = inventory.value.find((row) => row.id === item.inventory_id)
      if (inventoryItem && inventoryItem.price) {
        totalAmount += (inventoryItem.price || 0) * (item.quantity || 0)
      }
    })
    form.value.receivable_amount = totalAmount
  }

  async function save() {
    if (saving.value) return
    if (!modalEdit.value && !items.value.length) {
      showToast('请添加出库产品', 'error')
      return
    }
    saving.value = true
    try {
      const data = { ...form.value }
      if (modalEdit.value) {
        await api.updateShipment(modalId.value, data)
        showToast('更新成功')
      } else {
        data.items = items.value.filter((item) => item.inventory_id)
        if (!data.items.length) {
          showToast('请选择出库产品', 'error')
          saving.value = false
          return
        }
        const result = await api.createShipment(data)
        if (result.warning) showToast(result.warning, 'warn')
        else showToast('创建成功')
      }
      showModal.value = false
      await load()
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    } finally {
      saving.value = false
    }
  }

  async function del(shipment) {
    let impactInfo = ''
    try {
      const result = await api.shipmentImpact(shipment.id)
      if (result.items > 0) {
        impactInfo = '（含 ' + result.items + ' 个物品，将自动归还库存）'
      }
    } catch (error) {
      // non-blocking
    }
    if (!confirm('确定删除出库单 ' + shipment.shipment_no + ' 吗？' + impactInfo)) return
    try {
      await api.deleteShipment(shipment.id)
      showToast('删除成功')
      await load()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  async function viewDetail(shipment) {
    try {
      const data = await api.getShipment(shipment.id)
      detailShipment.value = data
      showDetail.value = true
    } catch (error) {
      showToast('加载详情失败', 'error')
    }
  }

  async function doReceive(shipment) {
    if (!confirm('确认签收 ' + shipment.shipment_no + ' 吗？')) return
    try {
      await api.receiveShipment(shipment.id, { receiver: '', receive_date: new Date().toISOString().slice(0, 10) })
      showToast('已签收')
      await load()
    } catch (error) {
      showToast(error.message || '签收失败', 'error')
    }
  }

  function openPayment(shipment) {
    payTarget.value = shipment
    payAmount.value = (shipment.receivable_amount || 0) - (shipment.paid_amount || 0)
    payMethod.value = ''
    payDate.value = new Date().toISOString().slice(0, 10)
    payRemark.value = ''
    showPayModal.value = true
  }

  async function doPayment() {
    if (!payAmount.value || payAmount.value <= 0) {
      showToast('请输入有效收款金额', 'error')
      return
    }
    try {
      await api.recordPayment(payTarget.value.id, {
        amount: payAmount.value,
        method: payMethod.value,
        remark: payRemark.value,
      })
      showToast('收款成功')
      showPayModal.value = false
      await load()
    } catch (error) {
      showToast(error.message || '收款失败', 'error')
    }
  }

  async function doComplete(shipment) {
    if (!confirm('确定完成出库单 ' + shipment.shipment_no + ' ？将扣减库存。')) return
    try {
      await api.completeShipment(shipment.id)
      showToast('出库完成')
      await load()
    } catch (error) {
      showToast(error.message || '出库失败', 'error')
    }
  }

  function prevPage() {
    if (page.value > 1) {
      page.value--
      load()
    }
  }

  function nextPage() {
    if (page.value * limit.value < total.value) {
      page.value++
      load()
    }
  }

  function exportExcel() {
    const url = '/api/shipments/export?keyword=' + encodeURIComponent(searchKeyword.value) + '&status=' + encodeURIComponent(filterStatus.value)
    window.open(url, '_blank')
  }

  function escapeHtml(str) {
    if (!str) return ''
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
  }

  function printDeliveryNote(shipment) {
    const now = new Date().toLocaleString('zh-CN')
    const detailItems = shipment.items || []
    const totalQuantity = detailItems.reduce((sum, item) => sum + (item.quantity || 0), 0)
    const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>送货单-${shipment.shipment_no}</title>
<style>body{font-family:'SimSun',serif;padding:40px;max-width:700px;margin:0 auto;color:#333}
h2{text-align:center;font-size:22px;margin-bottom:4px}h4{text-align:center;font-weight:400;color:#666;margin:0 0 24px}
.row{display:flex;justify-content:space-between;font-size:14px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;margin-top:20px}th,td{border:1px solid #333;padding:8px 10px;font-size:13px;text-align:center}
th{background:#f5f5f5}td{text-align:center}.right{text-align:right}.total-row{font-weight:700;font-size:14px}
.footer{margin-top:40px;display:flex;justify-content:space-between;font-size:14px}
@media print{body{padding:20px}@page{margin:15mm}}</style></head><body>
<h2>送 货 单</h2><h4>${now} | 单号: ${shipment.shipment_no}</h4>
<div class="row"><span><strong>客户:</strong> ${escapeHtml(shipment.customer) || '-'}</span><span><strong>联系人:</strong> ${escapeHtml(shipment.contact_person) || '-'}</span></div>
<div class="row"><span><strong>电话:</strong> ${escapeHtml(shipment.contact_phone) || '-'}</span><span><strong>地址:</strong> ${escapeHtml(shipment.address) || '-'}</span></div>
${shipment.remark ? '<p style="font-size:13px;color:#666"><strong>备注:</strong> ' + escapeHtml(shipment.remark) + '</p>' : ''}
<table><thead><tr><th>#</th><th>型号</th><th>产品名称</th><th>数量</th><th>单位</th><th>备注</th></tr></thead><tbody>
${detailItems.map((item, index) => '<tr><td>' + (index + 1) + '</td><td>' + (escapeHtml(item.product_model) || '-') + '</td><td>' + (escapeHtml(item.product_name) || '-') + '</td><td>' + item.quantity + '</td><td>' + (item.unit || '件') + '</td><td>' + (escapeHtml(item.remark) || '') + '</td></tr>').join('')}
<tr class="total-row"><td colspan="3" class="right">合计</td><td>${totalQuantity}</td><td colspan="2"></td></tr></tbody></table>
<div class="footer"><span>发货人签字: ___________</span><span>收货人签字: ___________</span></div>
<script>window.onload=function(){window.print();setTimeout(function(){window.close()},500)}</` + `script></body></html>`
    const win = window.open('', '_blank', 'width=800,height=600')
    win.document.write(html)
    win.document.close()
  }

  onMounted(async () => {
    await loadInventory()
    load()
  })

  return {
    shipments,
    loading,
    saving,
    total,
    page,
    limit,
    filterStatus,
    searchKeyword,
    inventory,
    showModal,
    modalEdit,
    form,
    items,
    detailShipment,
    showDetail,
    showPayModal,
    payTarget,
    payAmount,
    payMethod,
    payDate,
    payRemark,
    statusMap,
    paymentStatusMap,
    pendingCount,
    completedCount,
    receivableTotal,
    paidTotal,
    unpaidTotal,
    canCreate,
    canEdit,
    canDelete,
    load,
    openAdd,
    openEdit,
    addItem,
    removeItem,
    resetItem,
    focusItem,
    blurItem,
    updateItemSearch,
    updateItemQuantity,
    selectInventory,
    save,
    del,
    viewDetail,
    doReceive,
    openPayment,
    doPayment,
    doComplete,
    prevPage,
    nextPage,
    exportExcel,
    printDeliveryNote,
  }
}
