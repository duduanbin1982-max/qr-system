<!-- MaterialList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val">{{ materials.length }}</div><div class="s-label">物料总数</div></div></div>
      <div class="summary-item"><span class="s-icon">⚠️</span><div><div class="s-val text-danger">{{ lowStock.length }}</div><div class="s-label">低库存预警</div></div></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>📦 物料管理</h3>
        <div style="display:flex;gap:var(--space-2)">
          <input v-model="searchText" placeholder="搜索物料..." style="padding:6px 12px;border:1px solid #d9d9d9;border-radius:var(--radius-sm);font-size:var(--text-base);width:200px">
          <button class="btn btn-primary" @click="openCreate" v-if="canCreate">+ 新增物料</button>
          <button class="btn" style="background:#0891B2;color:#fff" @click="openSupplierAdd">🏭 供应商管理</button>
        </div>
      </div>
      <table class="data-table" v-if="materials.length">
        <thead>
          <tr>
            <th>名称</th><th>规格</th><th>材质</th><th>单位</th><th>库存量</th><th>单价</th><th>安全库存</th><th>供应商</th><th>库位</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in filteredMaterials" :key="m.id" :class="{ 'row-warn': m.quantity <= (m.safe_stock || 0) }">
            <td><strong>{{ m.name }}</strong></td>
            <td>{{ m.spec || '-' }}</td>
            <td><span style="color:var(--primary);font-size:var(--text-sm)">{{ m.material_type || '-' }}</span></td>
            <td>{{ m.unit }}</td>
            <td>
              <span :style="{color: m.quantity <= (m.safe_stock||0) ? 'var(--danger)' : '#333', fontWeight:'600'}">{{ m.quantity }}</span>
              <span v-if="m.quantity <= (m.safe_stock||0)" style="color:var(--danger);font-size:var(--text-xs);margin-left:4px">⚠</span>
            </td>
            <td>{{ m.unit_price != null ? '¥' + Number(m.unit_price).toFixed(2) : '-' }}</td>
            <td>{{ m.safe_stock || '-' }}</td>
            <td><span style="color:var(--teal);font-size:var(--text-xs)">{{ m.supplier_name || '-' }}</span></td>
            <td>{{ m.location || '-' }}</td>
            <td style="white-space:nowrap">
              <button v-if="canEdit" class="btn btn-sm" @click="openStock(m)" style="margin-right:4px">出入库</button>
              <button v-if="canEdit" class="btn btn-sm" @click="openConsume(m)" style="margin-right:4px;background:var(--danger);color:white">消耗</button>
              <button class="btn btn-sm" @click="viewLogs(m)" style="margin-right:4px">记录</button>
              <button class="btn btn-sm" @click="openEdit(m)" v-if="canEdit" style="margin-right:4px">编辑</button>
              <button class="btn btn-sm btn-danger" @click="remove(m)" v-if="canDelete">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else style="text-align:center;padding:40px;color:var(--text-placeholder)">暂无物料，点击「新增物料」开始</p>
    </div>

    <!-- Form Modal -->
    <div class="modal-overlay" v-if="showForm" >
      <div class="modal" style="max-width:600px">
        <div class="modal-header">{{ editing ? '编辑物料' : '新增物料' }}</div>
        <div class="modal-body">
          <!-- Low stock warning banner (edit mode only) -->
          <div v-if="showStockWarning" style="background:var(--danger);color:#fff;padding:10px 14px;border-radius:var(--radius-sm);margin-bottom:16px;font-size:var(--text-sm);display:flex;align-items:center;gap:8px">
            <span style="font-size:18px">&#x26A0;&#xFE0F;</span>
            <span>当前库存 <b>{{ form.quantity }}</b> {{ form.unit }}，低于安全库存 <b>{{ form.safe_stock }}</b> {{ form.unit }}，差额 <b>{{ Math.abs(stockGap) }}</b> {{ form.unit }}</span>
          </div>
          
          <div class="form-group"><label>名称 *</label><input v-model="form.name" class="form-input" placeholder="物料名称"></div>
          
          <div class="form-row">
            <div class="form-group" style="flex:1"><label>规格</label><input v-model="form.spec" class="form-input" placeholder="规格型号"></div>
            <div class="form-group" style="flex:1"><label>材质</label>
              <div>
                <input v-model="form.material_type" class="form-input" placeholder="Q235B / 304 / 45#钢">
                <div style="display:flex;gap:4px;margin-top:4px;flex-wrap:wrap">
                  <span v-for="mt in ['Q235B','Q345B','304','316L','45#','40Cr']" :key="mt" style="font-size:11px;padding:2px 6px;background:var(--bg-hover);border:1px solid var(--border-light);border-radius:3px;cursor:pointer;color:var(--text-placeholder)" @click="form.material_type=mt">{{ mt }}</span>
                </div>
              </div>
            </div>
          </div>
          
          <div class="form-row">
            <div class="form-group" style="flex:1">
              <label>单位</label>
              <input v-model="form.unit" class="form-input" placeholder="件/kg/m">
            </div>
            <div class="form-group" style="flex:1">
              <label>初始库存</label>
              <div style="display:flex;align-items:center;gap:6px">
                <input v-model.number="form.quantity" type="number" class="form-input" step="0.01" style="flex:1">
                <span style="font-size:var(--text-xs);color:var(--text-placeholder);white-space:nowrap">{{ form.unit }}</span>
              </div>
            </div>
            <div class="form-group" style="flex:1">
              <label>安全库存</label>
              <div style="display:flex;align-items:center;gap:6px">
                <input v-model.number="form.safe_stock" type="number" class="form-input" step="0.01" style="flex:1" :style="{borderColor: stockGap <= 0 && editing ? 'var(--danger)' : ''}">
                <span v-if="editing" :style="{fontSize:'14px',cursor:'default'}" :title="stockStatus.text">
                  <span v-if="stockGap > 0" style="color:var(--success)">&#x25CF;</span>
                  <span v-else-if="stockGap === 0" style="color:#f59e0b">&#x25CF;</span>
                  <span v-else style="color:var(--danger)">&#x25CF;</span>
                </span>
              </div>
            </div>
          </div>
          
          <div class="form-row">
            <div class="form-group" style="flex:1"><label>单价 (元)</label><input v-model.number="form.unit_price" type="number" class="form-input" step="0.01" placeholder="0.00"></div>
            <div class="form-group" style="flex:1"><label>库位</label><input v-model="form.location" class="form-input" placeholder="仓库/货架"></div>
          </div>
          
          <div class="form-group"><label>供应商</label>
            <div style="display:flex;gap:8px">
              <select v-model="form.supplier_id" class="form-input" style="flex:1">
                <option :value="null">-- 无 --</option>
                <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
              </select>
              <button type="button" class="btn btn-sm" style="white-space:nowrap;padding:8px 12px;background:var(--success);color:#fff;border:none;border-radius:var(--radius-sm)" @click="openSupplierAdd">+ 新增</button>
            </div>
          </div>
          
          <div class="form-group"><label>备注</label><textarea v-model="form.remark" class="form-input" rows="2" placeholder="备注信息"></textarea></div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="showForm=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>

    <!-- 新增供应商小弹窗 -->
    <div class="modal-overlay" v-if="showSupplierForm" >
      <div class="modal" style="max-width:520px">
        <div class="modal-header">🏭 供应商管理</div>
        <div class="modal-body">
          <div style="display:flex;gap:8px;margin-bottom:12px">
            <input v-model="supplierForm.name" class="form-input" placeholder="名称" style="flex:1">
            <input v-model="supplierForm.contact" class="form-input" placeholder="联系人" style="flex:1">
            <input v-model="supplierForm.phone" class="form-input" placeholder="电话" style="flex:1">
          </div>
          <button class="btn btn-primary btn-sm" @click="addSupplier" style="width:100%;margin-bottom:16px">➕ 新增供应商</button>
          <div v-if="suppliers.length" style="border-top:1px solid var(--border-light);padding-top:12px">
            <div style="font-size:13px;color:var(--text-placeholder);margin-bottom:8px">已有供应商 ({{ suppliers.length }})</div>
            <div v-for="s in suppliers" :key="s.id" style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--bg-hover);border-radius:6px;margin-bottom:4px">
              <div>
                <span style="font-weight:500">{{ s.name }}</span>
                <span v-if="s.contact" style="color:var(--text-placeholder);font-size:12px;margin-left:8px">{{ s.contact }}</span>
                <span v-if="s.phone" style="color:var(--text-placeholder);font-size:12px;margin-left:8px">{{ s.phone }}</span>
              </div>
              <button class="btn btn-sm" style="background:var(--danger);color:#fff;padding:4px 10px;font-size:12px" @click="deleteSupplier(s)">删除</button>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="showSupplierForm=false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Stock Modal -->
    <div class="modal-overlay" v-if="showStock" >
      <div class="modal" style="max-width:400px">
        <div class="modal-header">出入库 — {{ selectedMaterial?.name }}</div>
        <div class="modal-body">
          <p style="margin-bottom:var(--space-4);color:#666">当前库存: <strong>{{ selectedMaterial?.quantity }}</strong> {{ selectedMaterial?.unit }}</p>
          <div class="form-group"><label>类型</label>
            <select v-model="stockForm.type" class="form-input">
              <option value="in">入库 (+)</option>
              <option value="out">出库 (-)</option>
            </select>
          </div>
          <div class="form-group"><label>数量</label><input v-model.number="stockForm.quantity" type="number" class="form-input" step="0.01" min="0.01"></div>
          <div class="form-group"><label>操作人</label><input v-model="stockForm.operator_name" class="form-input" placeholder="姓名"></div>
          <div class="form-group"><label>备注</label><input v-model="stockForm.remark" class="form-input" placeholder="原因/用途"></div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="showStock=false">取消</button>
          <button class="btn btn-primary" @click="doStock">确认</button>
        </div>
      </div>
    </div>

    <!-- Logs Modal -->
    <div class="modal-overlay" v-if="logs.length" >
      <div class="modal" style="max-width:600px">
        <div class="modal-header">出入库记录 — {{ selectedMaterial?.name }}</div>
        <div class="modal-body">
          <table class="data-table" style="font-size:var(--text-sm)">
            <thead><tr><th>类型</th><th>数量</th><th>操作人</th><th>备注</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="l in logs" :key="l.id">
                <td><span :style="{color: l.type==='in'?'var(--success)':'var(--danger)',fontWeight:'600'}">{{ l.type==='in' ? '入库' : '出库' }}</span></td>
                <td>{{ l.type==='in' ? '+' : '-' }}{{ l.quantity }}</td>
                <td>{{ l.operator_name || '-' }}</td>
                <td>{{ l.remark || '-' }}</td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ l.created_at }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="logs=[]">关闭</button>
        </div>
      </div>
    </div>

    <!-- Consumption Modal -->
    <div class="modal-overlay" v-if="showConsume" >
      <div class="modal" style="max-width:600px">
        <div class="modal-header">物料消耗 — {{ selectedMaterial?.name }} <span style="font-size:var(--text-sm);color:var(--success);margin-left:12px">库存: {{ selectedMaterial?.quantity }} {{ selectedMaterial?.unit }}</span></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-group" style="flex:1">
              <label>订单关联</label>
              <div class="combobox">
                <input v-model="orderSearch" @input="searchOrders" @focus="searchOrders" placeholder="搜索订单号..." class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm)">
                <div v-if="orderDropdown && orderResults.length" class="combobox-dropdown">
                  <div v-for="o in orderResults" :key="o.id" class="combobox-item" @click="selectOrder(o)">
                    <span style="font-weight:600;color:var(--primary)">{{ o.order_no }}</span>
                    <span style="color:var(--text-placeholder);margin-left:8px;font-size:var(--text-xs)">{{ o.product_name }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="form-group" style="flex:1">
              <label>数量 *</label>
              <input v-model.number="consumeForm.quantity" type="number" class="form-input" step="0.01" min="0.01" placeholder="消耗数量">
            </div>
          </div>
          <div class="form-group"><label>备注</label><input v-model="consumeForm.notes" class="form-input" placeholder="用途说明"></div>
          <div class="form-group"><label>操作人</label><input v-model="consumeForm.operator_name" class="form-input" placeholder="姓名（留空用当前用户）"></div>

          <div v-if="consumptions.length" style="margin-top:16px;border-top:1px solid var(--bg-hover);padding-top:12px">
            <label style="font-size:var(--text-sm);font-weight:600;margin-bottom:var(--space-2);display:block">消耗记录</label>
            <table class="data-table" style="font-size:var(--text-xs)">
              <thead><tr><th>订单</th><th>产品</th><th>数量</th><th>操作人</th><th>备注</th><th>时间</th><th></th></tr></thead>
              <tbody>
                <tr v-for="c in consumptions" :key="c.id">
                  <td><span style="font-weight:600;color:var(--primary)">{{ c.order_no || '-' }}</span></td>
                  <td style="color:var(--text-placeholder)">{{ c.product_name || '-' }}</td>
                  <td style="font-weight:600;color:var(--danger)">-{{ c.quantity }}</td>
                  <td>{{ c.operator_name || '-' }}</td>
                  <td style="color:var(--text-placeholder);font-size:var(--text-xs-alt)">{{ c.notes || '-' }}</td>
                  <td style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ fmtDate(c.created_at) }}</td>
                  <td><button class="btn btn-sm" style="color:var(--danger);font-size:var(--text-xs-alt);padding:var(--space-1) 8px" @click="undoConsume(c)">撤销</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="showConsume=false">关闭</button>
          <button class="btn btn-primary" @click="doConsume">确认消耗</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export default {
  setup() {
    const materials = ref([])
    const logs = ref([])
    const suppliers = ref([])
    const loading = ref(true)
    const showForm = ref(false)
    const showStock = ref(false)
    const showConsume = ref(false)
    const editing = ref(null)
    const selectedMaterial = ref(null)
    const searchText = ref('')
    const showSupplierForm = ref(false)
    const supplierForm = ref({ name: '', contact: '', phone: '' })

    const form = ref({ name: '', spec: '', unit: '件', quantity: 0, unit_price: 0, safe_stock: 0, location: '', supplier_id: null, material_type: '', remark: '' })
    const stockForm = ref({ type: 'in', quantity: 0, remark: '', operator_name: '' })

    // Consumption state
    const consumptions = ref([])
    const consumeForm = ref({ order_id: null, process_id: null, quantity: 0, notes: '', operator_name: '' })
    const orderSearch = ref('')
    const orderResults = ref([])
    const orderDropdown = ref(false)

    const lowStock = computed(() => materials.value.filter(m => m.quantity <= (m.safe_stock || 0)))
    const filteredMaterials = computed(() => {
      if (!searchText.value) return materials.value
      const q = searchText.value.toLowerCase()
      return materials.value.filter(m =>
        (m.name || '').toLowerCase().includes(q) ||
        (m.spec || '').toLowerCase().includes(q) ||
        (m.location || '').toLowerCase().includes(q)
      )
    })

    // RBAC
    const canEdit   = computed(() => can('materials:manage'))
    const canDelete = computed(() => can('materials:manage'))
    const canCreate = computed(() => can('materials:manage'))

    // Dialog low stock warning computed properties
    const stockGap = computed(() => (form.value.quantity || 0) - (form.value.safe_stock || 0))
    const stockStatus = computed(() => {
        const gap = stockGap.value
        if (gap > 0) return { icon: 'passed', cls: 'stock-ok', text: 'Stock OK' }
        if (gap === 0) return { icon: 'warn', cls: 'stock-warn', text: 'Stock tight' }
        return { icon: 'danger', cls: 'stock-danger', text: 'Below safety by ' + Math.abs(gap) }
    })
    const showStockWarning = computed(() => editing.value && stockGap.value < 0)

    async function load() {
      loading.value = true
      try {
        const d = await api.get('/api/materials')
        materials.value = d.materials || []
      } catch (e) { showToast(e.message, 'error') }
      finally { loading.value = false }
    }

    function openCreate() {
      editing.value = null
      form.value = { name: '', spec: '', unit: '件', quantity: 0, unit_price: 0, safe_stock: 0, location: '', supplier_id: null, material_type: '', remark: '' }
      showForm.value = true
    }

    function openEdit(m) {
      editing.value = m.id
      form.value = (({ supplier_name, ...rest }) => {
            const f = { ...rest }
            if (f.supplier_id === '' || f.supplier_id === 0) f.supplier_id = null
            return f
        })(m)
      showForm.value = true
    }

    async function save() {
      if (!form.value.name.trim()) { showToast('名称必填', 'error'); return }
      try {
        const payload = { ...form.value }
        // Normalize all numeric fields
        for (const k of ['quantity', 'unit_price', 'safe_stock']) {
            if (payload[k] == null || payload[k] === '' || isNaN(payload[k])) payload[k] = 0
        }
        // Normalize supplier_id
        if (payload.supplier_id === '' || payload.supplier_id === 0 || payload.supplier_id == null) payload.supplier_id = null
        console.log('SAVE_DEBUG: payload=' + JSON.stringify(payload) + ' editing=' + editing.value)
        if (editing.value) await api.put('/api/materials/' + editing.value, payload)
        else await api.post('/api/materials', payload)
        showForm.value = false
        await load()
        showToast(editing.value ? '已更新' : '已创建')
      } catch (e) { showToast(e.message, 'error') }
    }

    async function remove(m) {
      let impactMsg = ''
      try {
        const res = await api.get('/api/materials/' + m.id + '/impact')
        if (res.refs > 0) {
          showToast('物料「' + m.name + '」有 ' + res.refs + ' 个关联，无法删除', 'warn')
          return
        }
      } catch(e) {}
      if (!confirm('确定删除物料「' + m.name + '」？')) return
      try {
        await api.del('/api/materials/' + m.id)
        await load()
        showToast('已删除')
      } catch (e) { showToast(e.message, 'error') }
    }

    function openStock(m) {
      selectedMaterial.value = m
      stockForm.value = { type: 'in', quantity: 0, remark: '', operator_name: '' }
      showStock.value = true
    }

    async function doStock() {
      if (stockForm.value.quantity <= 0) { showToast('数量必须大于0', 'error'); return }
      try {
        await api.post('/api/materials/' + selectedMaterial.value.id + '/stock', stockForm.value)
        showStock.value = false
        await load()
        showToast(stockForm.value.type === 'in' ? '已入库' : '已出库')
      } catch (e) { showToast(e.message, 'error') }
    }

    async function viewLogs(m) {
      selectedMaterial.value = m
      try {
        const d = await api.get('/api/materials/' + m.id + '/logs')
        logs.value = d.logs || []
      } catch (e) { showToast(e.message, 'error') }
    }

    // ===== Consumption =====
    async function openConsume(m) {
      selectedMaterial.value = m
      consumeForm.value = { order_id: null, process_id: null, quantity: 0, notes: '', operator_name: '' }
      orderSearch.value = ''; orderResults.value = []
      try {
        const d = await api.get('/api/materials/' + m.id + '/consumptions')
        consumptions.value = d.consumptions || []
      } catch (e) { consumptions.value = [] }
      showConsume.value = true
    }

    async function searchOrders() {
      if (!orderSearch.value) { orderResults.value = []; orderDropdown.value = false; return }
      try {
        const r = await api.get('/api/orders?keyword=' + encodeURIComponent(orderSearch.value) + '&limit=8')
        orderResults.value = r.orders || []; orderDropdown.value = orderResults.value.length > 0
      } catch (e) {}
    }

    function selectOrder(o) {
      consumeForm.value.order_id = o.id
      orderSearch.value = o.order_no + ' ' + (o.product_name || '')
      orderDropdown.value = false
    }

    function fmtDate(s) { if (!s) return ''; const m = s.match(/^\d{4}-\d{2}-\d{2}/); return m ? m[0] : s }

    async function doConsume() {
      if (consumeForm.value.quantity <= 0) { showToast('数量必须大于0', 'error'); return }
      try {
        await api.post('/api/materials/' + selectedMaterial.value.id + '/consumptions', consumeForm.value)
        showToast('消耗已记录')
        openConsume(selectedMaterial.value)
        await load()
      } catch (e) { showToast('操作失败', 'error') }
    }

    async function undoConsume(c) {
      if (!confirm('撤销消耗将恢复库存，确定？')) return
      try {
        await api.del('/api/materials/consumptions/' + c.id)
        showToast('已撤销')
        openConsume(selectedMaterial.value)
        await load()
      } catch (e) { showToast('操作失败', 'error') }
    }

    async function loadSuppliers() {
      try { const d = await api.get('/api/suppliers'); suppliers.value = d.suppliers || [] } catch (e) {}
    }

    function openSupplierAdd() {
      supplierForm.value = { name: '', contact: '', phone: '' }
      showSupplierForm.value = true
    }

    async function addSupplier() {
      if (!supplierForm.value.name.trim()) { showToast('供应商名称必填', 'error'); return }
      try {
        const r = await api.post('/api/suppliers', supplierForm.value)
        showSupplierForm.value = false
        await loadSuppliers()
        // 自动选中新创建的供应商
        if (r.id) {
          form.value.supplier_id = r.id
        } else if (suppliers.value.length > 0) {
          form.value.supplier_id = suppliers.value[suppliers.value.length - 1].id
        }
        showToast('供应商已添加')
      } catch (e) { showToast(e.message || '添加失败', 'error') }
    }

    async function deleteSupplier(s) {
      if (!confirm('确定删除供应商「' + s.name + '」？如有物料关联将无法删除。')) return
      try {
        await api.del('/api/suppliers/' + s.id)
        await loadSuppliers()
        showToast('供应商已删除')
      } catch (e) { showToast(e.message || '删除失败', 'error') }
    }

    onMounted(() => { load(); loadSuppliers() })

    return {
      materials, logs, suppliers, loading, showForm, showStock, showConsume, editing, selectedMaterial,
      form, stockForm, lowStock, searchText,
      consumptions, consumeForm, orderSearch, orderResults, orderDropdown,
      openCreate, openEdit, save, remove, openStock, doStock, viewLogs,
      openConsume, searchOrders, selectOrder, fmtDate, doConsume, undoConsume,
      showSupplierForm, supplierForm, openSupplierAdd, addSupplier, deleteSupplier,
      canEdit, canDelete, canCreate, filteredMaterials, stockGap, stockStatus, showStockWarning,
    }
  }
}
</script>
