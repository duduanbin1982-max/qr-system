// ShipmentList Component — 发货管理
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { auth, can } from '../../auth.js'

export default {
  template: '#shipment-list-template',
  setup() {
    const shipments = ref([])
    const loading = ref(true)
    const saving = ref(false)
    const total = ref(0)
    const page = ref(1)
    const limit = ref(20)
    const filterStatus = ref('')
    const searchKeyword = ref('')

    // RBAC
    const canCreate = computed(() => can('shipments:create'))
    const canEdit   = computed(() => can('shipments:edit'))
    const canDelete = computed(() => can('shipments:delete'))

    // 库存下拉
    const inventory = ref([])

    // 模态框
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ shipment_no:'', customer:'', contact_person:'', contact_phone:'', address:'', remark:'', status:'pending' })
    const items = ref([]) // [{inventory_id, product_model, product_name, quantity, unit, remark}]

    // 详情模态框
    const detailShipment = ref(null)
    const showDetail = ref(false)

    const statusMap = {
      'pending':   { label:'待出库', cls:'badge-info' },
      'completed': { label:'已出库', cls:'badge-success' },
    }

    const pendingCount  = ref(0)
    const completedCount = ref(0)

    async function load() {
      loading.value = true
      try {
        const params = { page: page.value, limit: limit.value }
        if (filterStatus.value) params.status = filterStatus.value
        if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
        const d = await api.listShipments(params)
        shipments.value = d.shipments || []
        total.value = d.total || 0
        pendingCount.value = d.pending_count ?? 0
        completedCount.value = d.completed_count ?? 0
      } catch(e) { showToast(e.message || '加载失败','error') }
      finally { loading.value = false }
    }

    async function loadInventory() {
      try { const d = await api.listInventory(); inventory.value = d.items || [] } catch(e) { showToast('加载库存列表失败', 'warn') }
    }

    async function openAdd() {
      form.value = { shipment_no:'', customer:'', contact_person:'', contact_phone:'', address:'', remark:'', status:'pending' }
      items.value = []
      modalEdit.value = false; modalId.value = null
      try { const d = await api.draftShipment(); form.value.shipment_no = d.shipment_no } catch(e) { showToast('自动生成出库单号失败，请手动输入', 'warn') }
      showModal.value = true
    }

    async function openEdit(s) {
      form.value = {
        shipment_no: s.shipment_no,
        customer: s.customer || '',
        contact_person: s.contact_person || '',
        contact_phone: s.contact_phone || '',
        address: s.address || '',
        remark: s.remark || '',
        status: s.status || 'pending'
      }
      items.value = [] // 编辑模式清空明细，防止新建残留
      modalEdit.value = true; modalId.value = s.id
      showModal.value = true
    }

    function addItem() { items.value.push({ inventory_id:'', product_model:'', product_name:'', quantity:1, unit:'件', remark:'' }) }

    function removeItem(idx) { items.value.splice(idx, 1) }

    function onInvChange(idx) {
      const inv = inventory.value.find(i => i.id === items.value[idx].inventory_id)
      if (inv) {
        items.value[idx].product_model = inv.product_model
        items.value[idx].product_name = inv.product_name
        items.value[idx].unit = inv.unit || '件'
      }
    }

    async function save() {
      if (saving.value) return
      if (!modalEdit.value && !items.value.length) { showToast('请添加出库产品','error'); return }
      saving.value = true
      try {
        const data = { ...form.value }
        if (modalEdit.value) {
          await api.updateShipment(modalId.value, data)
          showToast('更新成功')
        } else {
          data.items = items.value.filter(i => i.inventory_id)
          if (!data.items.length) { showToast('请选择出库产品','error'); saving.value = false; return }
          const result = await api.createShipment(data)
          if (result.warning) showToast(result.warning, 'warn')
          else showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) { showToast(e.message || '保存失败','error') }
      finally { saving.value = false }
    }

    async function del(s) {
      const msg = s.status === 'completed' ? '已完成出库（将自动归还库存），' : ''
      if (!confirm(msg + '确定删除出库单 ' + s.shipment_no + ' 吗？')) return
      try { await api.deleteShipment(s.id); showToast('删除成功'); await load() }
      catch(e) { showToast(e.message || '删除失败','error') }
    }

    async function viewDetail(s) {
      try {
        const d = await api.getShipment(s.id)
        detailShipment.value = d
        showDetail.value = true
      } catch(e) { showToast('加载详情失败','error') }
    }

    async function doComplete(s) {
      if (!confirm('确定完成出库单 ' + s.shipment_no + ' ？将扣减库存。')) return
      try { await api.completeShipment(s.id); showToast('出库完成'); await load() }
      catch(e) { showToast(e.message || '出库失败','error') }
    }

    function prevPage() { if (page.value > 1) { page.value--; load() } }
    function nextPage() { if (page.value * limit.value < total.value) { page.value++; load() } }

    function printDeliveryNote(s) {
      const now = new Date().toLocaleString('zh-CN')
      const items = s.items || []
      const totalQty = items.reduce((sum, it) => sum + (it.quantity || 0), 0)
      const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>送货单-${s.shipment_no}</title>
<style>body{font-family:'SimSun',serif;padding:40px;max-width:700px;margin:0 auto;color:#333}
h2{text-align:center;font-size:22px;margin-bottom:4px}h4{text-align:center;font-weight:400;color:#666;margin:0 0 24px}
.row{display:flex;justify-content:space-between;font-size:14px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;margin-top:20px}th,td{border:1px solid #333;padding:8px 10px;font-size:13px;text-align:center}
th{background:#f5f5f5}td{text-align:center}.right{text-align:right}.total-row{font-weight:700;font-size:14px}
.footer{margin-top:40px;display:flex;justify-content:space-between;font-size:14px}
@media print{body{padding:20px}@page{margin:15mm}}</style></head><body>
<h2>送 货 单</h2><h4>${now} | 单号: ${s.shipment_no}</h4>
<div class="row"><span><strong>客户:</strong> ${s.customer || '-'}</span><span><strong>联系人:</strong> ${s.contact_person || '-'}</span></div>
<div class="row"><span><strong>电话:</strong> ${s.contact_phone || '-'}</span><span><strong>地址:</strong> ${s.address || '-'}</span></div>
${s.remark ? '<p style="font-size:13px;color:#666"><strong>备注:</strong> ' + s.remark + '</p>' : ''}
<table><thead><tr><th>#</th><th>型号</th><th>产品名称</th><th>数量</th><th>单位</th><th>备注</th></tr></thead><tbody>
${items.map((it, i) => '<tr><td>' + (i+1) + '</td><td>' + (it.product_model || '-') + '</td><td>' + (it.product_name || '-') + '</td><td>' + it.quantity + '</td><td>' + (it.unit || '件') + '</td><td>' + (it.remark || '') + '</td></tr>').join('')}
<tr class="total-row"><td colspan="3" class="right">合计</td><td>${totalQty}</td><td colspan="2"></td></tr></tbody></table>
<div class="footer"><span>发货人签字: ___________</span><span>收货人签字: ___________</span></div>
<script>window.onload=function(){window.print();setTimeout(function(){window.close()},500)}</` + `script></body></html>`
      const w = window.open('', '_blank', 'width=800,height=600')
      w.document.write(html); w.document.close()
    }

    onMounted(async () => { await loadInventory(); load() })

    return {
      shipments, loading, saving, total, page, limit, filterStatus, searchKeyword, statusMap,
      pendingCount, completedCount, inventory,
      showModal, modalEdit, form, items, openAdd, openEdit, addItem, removeItem, onInvChange, save, del,
      showDetail, detailShipment, viewDetail, doComplete, printDeliveryNote,
      prevPage, nextPage, load, auth, canCreate, canEdit, canDelete
    }
  }
}
