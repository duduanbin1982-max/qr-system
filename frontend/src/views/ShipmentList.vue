<!-- ShipmentList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🚚</span><div><div class="s-val">{{ total }}</div><div class="s-label">出库单总数</div></div></div>
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val" style="color:var(--warning)">{{ pendingCount }}</div><div class="s-label">待出库</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ completedCount }}</div><div class="s-label">已出库</div></div></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>🚚 发货管理</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <select class="form-input" v-model="filterStatus" @change="page=1;load()" style="border:1px solid var(--border);border-radius:var(--radius-md);padding:var(--space-2) 12px;font-size:var(--text-base);background:white;cursor:pointer;width:100px">
            <option value="">全部</option>
            <option value="pending">待出库</option>
            <option value="completed">已出库</option>
          </select>
          <div class="search-box" style="background:var(--bg-hover);border-radius:var(--radius-md);display:flex;align-items:center;padding:0 10px">
            <span>🔍</span>
            <input class="form-input" v-model="searchKeyword" placeholder="搜索单号/客户..." @keyup.enter="load" style="border:none;background:transparent;outline:none;padding:var(--space-2) 6px;font-size:var(--text-base);width:160px;box-shadow:none">
          </div>
          <button class="btn btn-default btn-sm" @click="load">搜索</button>
                      <button class="btn btn-primary btn-sm" @click="openAdd">+ 新建出库单</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="shipments.length" class="data-table" style="min-width:850px">
            <thead>
              <tr>
                <th style="width:30px"></th>
                <th style="min-width:120px">出库单号</th>
                <th style="min-width:90px">客户</th>
                <th style="min-width:70px">联系人</th>
                <th style="width:60px;text-align:center">物品数</th>
                <th style="width:60px;text-align:center">总量</th>
                <th style="width:70px;text-align:center">状态</th>
                <th style="width:140px;text-align:center">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="s in shipments" :key="s.id">
                <tr @click="viewDetail(s)" style="cursor:pointer">
                  <td style="text-align:center;font-size:var(--text-xs);color:var(--text-placeholder)">▶</td>
                  <td><code style="font-size:var(--text-xs);font-weight:600">{{ s.shipment_no }}</code></td>
                  <td style="font-weight:500">{{ s.customer || '-' }}</td>
                  <td style="font-size:var(--text-sm)">{{ s.contact_person || '-' }}</td>
                  <td style="text-align:center">{{ s.item_count || 0 }}</td>
                  <td style="text-align:center;font-weight:600">{{ s.total_quantity }}</td>
                  <td style="text-align:center"><span class="badge" :class="statusMap[s.status]?.cls||'badge-info'" style="font-size:var(--text-xs-alt)">{{ statusMap[s.status]?.label||s.status }}</span></td>
                  <td style="text-align:center">
                    <div class="o-actions" style="justify-content:center" @click.stop>
                      <button v-if="s.status==='pending'" class="btn btn-success btn-sm" @click="doComplete(s)" style="font-size:var(--text-xs-alt);padding:var(--space-1) 8px">✅完成</button>
                      <span class="o-abtn o-edit" @click="openEdit(s)" title="编辑">✏️</span>
                      <span class="o-abtn o-del" @click="del(s)" title="删除">🗑️</span>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-icon">🚚</div><div class="empty-text">暂无出库单</div></div>
        </div>
        <div v-if="total > limit" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0">
          <button class="btn btn-default btn-sm" @click="prevPage" :disabled="page <= 1">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total/limit) }} 页，共 {{ total }} 条</span>
          <button class="btn btn-default btn-sm" @click="nextPage" :disabled="page * limit >= total">下一页</button>
        </div>
      </div>
    </div>

    <!-- 新增模态框 -->
    <div v-if="showModal && !modalEdit" class="modal-overlay" >
      <div class="modal" style="max-width:650px">
        <div class="modal-header"><span>新建出库单</span><span class="modal-close" @click="showModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col" style="flex:2"><div class="form-group"><label>出库单号</label><input class="form-input" v-model="form.shipment_no" placeholder="自动生成" disabled></div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>客户</label><input class="form-input" v-model="form.customer" placeholder="客户名称"></div></div>
            <div class="form-col"><div class="form-group"><label>联系人</label><input class="form-input" v-model="form.contact_person" placeholder="联系人"></div></div>
            <div class="form-col"><div class="form-group"><label>电话</label><input class="form-input" v-model="form.contact_phone" placeholder="联系电话"></div></div>
          </div>
          <div class="form-group"><label>地址</label><input class="form-input" v-model="form.address" placeholder="收货地址"></div>
          <div class="form-group"><label>备注</label><input class="form-input" v-model="form.remark" placeholder="备注"></div>
          <!-- 出库产品 -->
          <div style="margin-top:16px;border-top:1px solid var(--border-light);padding-top:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-2)">
              <label style="font-weight:600;font-size:var(--text-base)">出库产品</label>
              <button class="btn btn-default btn-sm" @click="addItem" style="font-size:var(--text-xs);padding:var(--space-1) 12px">+ 添加</button>
            </div>
            <div v-if="items.length">
              <div v-for="(it, idx) in items" :key="idx" style="display:flex;gap:var(--space-2);align-items:center;margin-bottom:6px;padding:var(--space-2);background:var(--bg-table-header);border-radius:var(--radius-md);flex-wrap:wrap">
                <select class="form-input" v-model="it.inventory_id" @change="onInvChange(idx)" style="flex:2;font-size:var(--text-xs);min-width:120px">
                  <option value="">-- 选择库存 --</option>
                  <option v-for="inv in inventory" :key="inv.id" :value="inv.id">{{ inv.product_model }} ({{ inv.quantity }}{{ inv.unit }})</option>
                </select>
                <input class="form-input" v-model.number="it.quantity" type="number" min="1" placeholder="数量" style="width:60px;font-size:var(--text-xs);text-align:center">
                <span @click="removeItem(idx)" style="color:var(--danger);cursor:pointer;font-size:var(--text-base)">✕</span>
              </div>
            </div>
            <p v-else style="font-size:var(--text-xs);color:var(--text-placeholder);text-align:center;padding:var(--space-3)">暂未添加出库产品</p>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">创建出库单</button>
        </div>
      </div>
    </div>

    <!-- 编辑模态框 -->
    <div v-if="showModal && modalEdit" class="modal-overlay" >
      <div class="modal" style="max-width:500px">
        <div class="modal-header"><span>编辑出库单 — {{ form.shipment_no }}</span><span class="modal-close" @click="showModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>客户</label><input class="form-input" v-model="form.customer"></div></div>
            <div class="form-col"><div class="form-group"><label>状态</label>
              <select class="form-input" v-model="form.status"><option value="pending">待出库</option><option value="completed">已出库</option></select>
            </div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>联系人</label><input class="form-input" v-model="form.contact_person"></div></div>
            <div class="form-col"><div class="form-group"><label>电话</label><input class="form-input" v-model="form.contact_phone"></div></div>
          </div>
          <div class="form-group"><label>地址</label><input class="form-input" v-model="form.address"></div>
          <div class="form-group"><label>备注</label><input class="form-input" v-model="form.remark"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>

    <!-- 详情模态框 -->
    <div v-if="showDetail" class="modal-overlay" >
      <div class="modal" style="max-width:650px">
        <div class="modal-header"><span>📋 {{ detailShipment?.shipment_no }}</span><span class="modal-close" @click="showDetail=false">&times;</span></div>
        <div class="modal-body">
          <div v-if="detailShipment" style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-2);font-size:var(--text-base);margin-bottom:var(--space-4)">
            <div><span style="color:var(--text-placeholder)">客户：</span>{{ detailShipment.customer || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">联系人：</span>{{ detailShipment.contact_person || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">电话：</span>{{ detailShipment.contact_phone || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">地址：</span>{{ detailShipment.address || '-' }}</div>
          </div>
          <table v-if="detailShipment?.items?.length" class="data-table">
            <thead><tr><th>库存型号</th><th>产品名</th><th style="width:60px;text-align:center">数量</th><th>单位</th><th>备注</th></tr></thead>
            <tbody>
              <tr v-for="it in detailShipment.items" :key="it.id">
                <td><code style="font-size:var(--text-xs-alt)">{{ it.product_model }}</code></td>
                <td>{{ it.product_name || '-' }}</td>
                <td style="text-align:center;font-weight:600">{{ it.quantity }}</td>
                <td>{{ it.unit }}</td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ it.remark || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:var(--space-5)">无出库明细</p>
          <div v-if="detailShipment" style="text-align:right;margin-top:16px;padding-top:12px;border-top:1px solid var(--border-light)">
            <button class="btn-primary btn-sm" @click="printDeliveryNote(detailShipment)" style="padding:var(--space-2) 20px;font-size:var(--text-sm)">🖨️ 打印送货单</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { auth, can } from '@/lib/auth.js'

export default {
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
      try {
        const res = await api.get('/api/shipments/' + s.id + '/impact')
        if (res.items > 0) {
          showToast('出库单「' + s.shipment_no + '」包含 ' + res.items + ' 个物品，请先清空', 'warn')
          return
        }
      } catch(e) {}
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

    function escapeHtml(str) {
      if (!str) return ''
      return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')
    }

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
<div class="row"><span><strong>客户:</strong> ${escapeHtml(s.customer) || '-'}</span><span><strong>联系人:</strong> ${escapeHtml(s.contact_person) || '-'}</span></div>
<div class="row"><span><strong>电话:</strong> ${escapeHtml(s.contact_phone) || '-'}</span><span><strong>地址:</strong> ${escapeHtml(s.address) || '-'}</span></div>
${s.remark ? '<p style="font-size:13px;color:#666"><strong>备注:</strong> ' + escapeHtml(s.remark) + '</p>' : ''}
<table><thead><tr><th>#</th><th>型号</th><th>产品名称</th><th>数量</th><th>单位</th><th>备注</th></tr></thead><tbody>
${items.map((it, i) => '<tr><td>' + (i+1) + '</td><td>' + (escapeHtml(it.product_model) || '-') + '</td><td>' + (escapeHtml(it.product_name) || '-') + '</td><td>' + it.quantity + '</td><td>' + (it.unit || '件') + '</td><td>' + (escapeHtml(it.remark) || '') + '</td></tr>').join('')}
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
</script>
