<!-- InspectionList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val">{{ stats.total }}</div><div class="s-label">总检验</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ stats.pass_count }}</div><div class="s-label">合格</div></div></div>
      <div class="summary-item"><span class="s-icon">❌</span><div><div class="s-val text-danger">{{ stats.fail_count }}</div><div class="s-label">不合格</div></div></div>
      <div class="summary-item"><span class="s-icon">📅</span><div><div class="s-val text-info">{{ stats.today_count }}</div><div class="s-label">今日检验</div></div></div>
    </div>

    <!-- Pareto: 不良品分布 -->
    <div v-if="pareto.items.length" class="card" style="border-radius:var(--radius-lg);padding:18px 24px;margin-bottom:var(--space-4)">
      <h4 style="margin:0 0 14px;font-size:15px;font-weight:700;color:var(--text-primary)">📊 不良品帕累托图（共 {{ pareto.grand_total }} 件）</h4>
      <div v-for="(p, i) in pareto.items" :key="p.category" style="margin-bottom:10px">
        <div style="display:flex;align-items:center;margin-bottom:3px">
          <span style="font-size:var(--text-sm);font-weight:500;width:80px;color:var(--text-secondary)">{{ p.category }}</span>
          <span style="font-size:var(--text-xs);color:var(--text-placeholder);width:50px;text-align:right;margin-right:8px">{{ p.quantity }}件</span>
          <div style="flex:1;background:var(--bg-hover);border-radius:var(--radius-sm);height:20px;overflow:hidden;position:relative">
            <div :style="{width:p.pct+'%',background:'linear-gradient(90deg,'+(i===0?'var(--danger)':i===1?'var(--warning)':'var(--warning)')+',var(--warning))',height:'100%',borderRadius:'6px',transition:'width .4s'}"></div>
          </div>
          <span style="font-size:var(--text-xs-alt);color:var(--text-placeholder);width:65px;text-align:right;margin-left:8px">{{ p.pct }}% / {{ p.cum_pct }}%</span>
        </div>
      </div>
    </div>

    <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
      <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap;padding:var(--space-3) 20px">
        <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:var(--space-2);margin:0">
          <span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--teal),var(--teal-dark));border-radius:var(--radius-md);font-size:var(--text-lg);color:white">🔍</span>
          质量检验
        </h3>
        <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto;flex-wrap:wrap">
          <input v-model="search" @keyup.enter="applyFilter" placeholder="搜索订单号/工序..." class="form-input" style="width:160px;font-size:var(--text-sm);padding:6px 10px">
          <select v-model="filterType" class="form-input" style="width:110px;font-size:var(--text-sm);padding:6px 8px" @change="applyFilter">
            <option value="">全部类型</option>
            <option value="first_article">首件检验</option>
            <option value="in_process">过程检验</option>
            <option value="final">终检</option>
          </select>
          <select v-model="filterResult" class="form-input" style="width:100px;font-size:var(--text-sm);padding:6px 8px" @change="applyFilter">
            <option value="">全部结果</option>
            <option value="pass">合格</option>
            <option value="fail">不合格</option>
            <option value="partial">部分合格</option>
          </select>
          <input v-model="dateFrom" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
          <span style="color:var(--text-placeholder);font-size:var(--text-xs)">至</span>
          <input v-model="dateTo" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
          <button class="btn-add" style="margin-left:4px;padding:var(--space-2) 16px;font-size:var(--text-sm)" @click="openCreate" v-if="canCreate">+ 新建检验</button>
        </div>
      </div>

      <div v-if="loading" style="text-align:center;padding:60px;color:var(--text-placeholder)">⏳ 加载中...</div>
      <div v-else-if="!items.length" style="text-align:center;padding:60px;color:var(--text-placeholder)"><p style="font-size:48px;margin:0">🔍</p><p style="margin-top:12px">暂无检验记录</p></div>
      <div v-else style="padding:0 20px 20px">
        <table style="width:100%;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:120px">订单号</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">工序</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">类型</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:60px">检验数</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:60px">合格</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:60px">不合格</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:70px">结果</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:70px">检验员</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">备注</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:100px">时间</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:60px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="it in items" :key="it.id" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm)">
              <td style="padding:var(--space-2) 12px">
                <div style="font-weight:600;color:var(--primary)">{{ it.order_no }}</div>
                <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.product_name }}</div>
              </td>
              <td style="padding:var(--space-2) 12px;color:var(--primary-accent);font-weight:500">{{ it.process_name }}</td>
              <td style="padding:var(--space-2) 12px">
                <span :style="{background:it.inspection_type==='first_article'?'var(--info-light)':it.inspection_type==='in_process'?'var(--warning-lighter)':'var(--success-lighter)',color:it.inspection_type==='first_article'?'var(--info)':it.inspection_type==='in_process'?'var(--warning)':'var(--success)',padding:'2px 8px',borderRadius:'4px',fontSize:'12px'}">{{ typeLabel(it.inspection_type) }}</span>
              </td>
              <td style="padding:var(--space-2) 12px;text-align:center">{{ it.quantity_checked }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center;color:var(--success);font-weight:500">{{ it.quantity_passed }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center;color:var(--danger);font-weight:500">{{ it.quantity_failed }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center">
                <span :style="{background:it.result==='pass'?'var(--success-lighter)':it.result==='fail'?'var(--danger-light)':'var(--warning-lighter)',color:it.result==='pass'?'var(--success)':it.result==='fail'?'var(--danger)':'var(--warning)',padding:'2px 8px',borderRadius:'4px',fontSize:'12px',fontWeight:'500'}">{{ resultLabel(it.result) }}</span>
              </td>
              <td style="padding:var(--space-2) 12px;color:var(--text-secondary)">{{ it.inspector_name || '-' }}</td>
              <td style="padding:var(--space-2) 12px;color:var(--text-placeholder);font-size:var(--text-xs);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ it.notes || '-' }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center;font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ fmtDate(it.inspected_at) }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center">
                <button @click="openEdit(it)" v-if="canEdit" class="btn-icon-edit btn-icon-sm" style="font-size:var(--text-xs);margin-right:4px" title="编辑">✏️</button>
                <button @click="doDelete(it)" v-if="canDelete" class="btn-icon-del btn-icon-sm" style="font-size:var(--text-xs)" title="删除">🗑</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="total > perPage" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0 0">
          <button class="btn-default btn-sm" @click="load(page-1)" :disabled="page<=1">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total/perPage) }} 页（共 {{ total }} 条）</span>
          <button class="btn-default btn-sm" @click="load(page+1)" :disabled="page*perPage >= total">下一页</button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showModal" style="position:fixed;inset:0;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:1000" >
      <div style="background:white;border-radius:var(--radius-lg);padding:28px;width:480px;max-width:90vw;box-shadow:0 12px 40px rgba(0,0,0,0.15)">
        <h3 style="margin:0 0 20px;font-size:17px;color:var(--text-primary)">{{ isEdit ? '编辑检验记录' : '新建检验记录' }}</h3>

        <label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">订单</label>
        <div class="combobox" style="margin-bottom:14px">
          <input v-model="orderSearch" @input="searchOrders" @focus="searchOrders" placeholder="搜索订单号..." class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm)" :disabled="isEdit">
          <div v-if="orderDropdown && orders.length" class="combobox-dropdown">
            <div v-for="o in orders" :key="o.id" class="combobox-item" @click="selectOrder(o)">
              <span style="font-weight:600;color:var(--primary)">{{ o.order_no }}</span>
              <span style="color:var(--text-placeholder);margin-left:8px;font-size:var(--text-xs)">{{ o.product_name }} · {{ o.customer_name || o.customer }}</span>
            </div>
          </div>
        </div>

        <label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">工序</label>
        <div class="combobox" style="margin-bottom:14px">
          <input v-model="processSearch" @input="searchProcesses" @focus="searchProcesses" placeholder="搜索工序名称..." class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm)" :disabled="isEdit">
          <div v-if="processDropdown && processes.length" class="combobox-dropdown">
            <div v-for="p in processes" :key="p.id" class="combobox-item" @click="selectProcess(p)">
              <span>{{ p.process_name }}</span>
            </div>
          </div>
        </div>

        <label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">检验类型</label>
        <select v-model="form.inspection_type" class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm);margin-bottom:14px">
          <option value="first_article">首件检验</option>
          <option value="in_process">过程检验</option>
          <option value="final">终检</option>
        </select>

        <div style="display:flex;gap:var(--space-3);margin-bottom:14px">
          <div style="flex:1"><label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">检验数量</label><input v-model.number="form.quantity_checked" type="number" class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm)" @input="onCheckedQtyManual"></div>
          <div style="flex:1"><label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">合格</label><input v-model.number="form.quantity_passed" type="number" class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm)" @input="autoCalcQty"></div>
          <div style="flex:1"><label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">不合格</label><input v-model.number="form.quantity_failed" type="number" class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm)" @input="autoCalcQty"></div>
        </div>

        <div v-if="form.quantity_failed > 0" style="display:flex;gap:var(--space-3);margin-bottom:14px">
          <div style="flex:1"><label style="font-size:var(--text-sm);color:var(--danger);display:block;margin-bottom:var(--space-1)">缺陷类别</label>
            <select v-model="form.defect_category" class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm);border-color:var(--danger-lighter)">
              <option value="">-- 请选择 --</option>
              <option v-for="c in defectCategories" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
          <div style="flex:1"><label style="font-size:var(--text-sm);color:var(--danger);display:block;margin-bottom:var(--space-1)">缺陷数量</label>
            <input v-model.number="form.defect_quantity" type="number" class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm);border-color:var(--danger-lighter)" min="0">
          </div>
        </div>

        <label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">备注</label>
        <input v-model="form.notes" placeholder="检验备注..." class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm);margin-bottom:14px">

        <label style="font-size:var(--text-sm);color:var(--text-placeholder);display:block;margin-bottom:var(--space-1)">检验日期</label>
        <input v-model="form.inspected_at" type="date" class="form-input" style="width:100%;box-sizing:border-box;font-size:var(--text-sm);margin-bottom:var(--space-5)">

        <div style="display:flex;gap:var(--space-3);justify-content:flex-end">
          <button @click="showModal=false" class="btn-default btn-sm" style="padding:var(--space-2) 20px">取消</button>
          <button @click="doSave" class="btn-success" style="padding:var(--space-2) 24px;font-size:var(--text-sm)">{{ isEdit ? '保存' : '提交' }}</button>
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
    const items = ref([])
    const loading = ref(false)
    const stats = ref({ total: 0, today_count: 0, pass_count: 0, fail_count: 0 })
    const search = ref('')
    const filterType = ref('')
    const filterResult = ref('')
    const dateFrom = ref('')
    const dateTo = ref('')
    const page = ref(1)
    const total = ref(0)
    const perPage = 20
    const editing = ref(null)
    const defectCategories = ref(['尺寸超差', '外观缺陷', '材质问题', '焊接缺陷', '装配不良', '其他'])

    // RBAC
    const canEdit   = computed(() => can('quality:edit'))
    const canDelete = computed(() => can('quality:delete'))
    const canCreate = computed(() => can('quality:create'))

    // Create/Edit modal
    const showModal = ref(false); const isEdit = ref(false)
    const form = ref({})
    const orders = ref([]); const processes = ref([])
    const orderSearch = ref(''); const processSearch = ref('')
    const orderDropdown = ref(false); const processDropdown = ref(false)

    function fmtDate(s) { if (!s) return ''; const m = s.match(/^\d{4}-\d{2}-\d{2}/); return m ? m[0] : s }
    function fmtDatetime(s) { if (!s) return ''; const m = s.match(/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}/); return m ? m[0] : s }
    function typeLabel(t) { const f = INSPECTION_TYPES.find(x => x.value === t); return f ? f.label : t }
    function resultLabel(r) { return RESULT_LABELS[r] || r }

    async function load(p = 1) {
      loading.value = true; page.value = p
      const params = []
      if (search.value) params.push('search=' + encodeURIComponent(search.value))
      if (filterType.value) params.push('type=' + filterType.value)
      if (filterResult.value) params.push('result=' + filterResult.value)
      if (dateFrom.value) params.push('from=' + dateFrom.value)
      if (dateTo.value) params.push('to=' + dateTo.value)
      params.push('page=' + p, 'per_page=' + perPage)
      try {
        const r = await api.get('/api/quality/inspections?' + params.join('&'))
        if (r.ok) { items.value = r.items; total.value = r.total }
      } catch (e) { showToast('加载失败', 'error') }
      finally { loading.value = false }
    }

    async function loadStats() {
      try { const r = await api.get('/api/quality/inspections/stats'); if (r.ok) stats.value = r } catch (e) {}
    }

    async function searchOrders() {
      if (!orderSearch.value) { orders.value = []; orderDropdown.value = false; return }
      try {
        const r = await api.get('/api/orders?keyword=' + encodeURIComponent(orderSearch.value) + '&limit=10')
        if (r.ok) { orders.value = r.orders || []; orderDropdown.value = orders.value.length > 0 }
      } catch (e) {}
    }

    let allProcessesCache = null

    async function loadProcessesCache() {
      try {
        const r = await api.get('/api/processes')
        if (r.ok) allProcessesCache = (r.processes || []).filter(p => p.status === 'active')
      } catch (e) {}
    }

    function searchProcesses() {
      if (!allProcessesCache) return
      const q = (processSearch.value || '').toLowerCase()
      processes.value = q
        ? allProcessesCache.filter(p => (p.process_name || '').toLowerCase().includes(q))
        : allProcessesCache
      processDropdown.value = processes.value.length > 0
    }

    function selectOrder(o) { form.value.order_id = o.id; orderSearch.value = o.order_no + ' ' + (o.product_name || ''); orderDropdown.value = false }
    function selectProcess(p) { form.value.process_id = p.id; processSearch.value = p.process_name; processDropdown.value = false }

    let userSetCheckedQty = false

    function autoCalcQty() {
      if (!userSetCheckedQty) {
        form.value.quantity_checked = (form.value.quantity_passed || 0) + (form.value.quantity_failed || 0)
      }
    }

    function onCheckedQtyManual() {
      userSetCheckedQty = form.value.quantity_checked > 0
    }

    function openCreate() {
      userSetCheckedQty = false
      isEdit.value = false
      form.value = { order_id: null, process_id: null, inspection_type: 'first_article', quantity_checked: 0, quantity_passed: 0, quantity_failed: 0, defect_category: '', defect_quantity: 0, notes: '', inspected_at: '' }
      orderSearch.value = ''; processSearch.value = ''; orders.value = []; processes.value = []
      showModal.value = true
    }

    function openEdit(item) {
      isEdit.value = true
      form.value = { ...item }
      orderSearch.value = item.order_no + ' ' + (item.product_name || '')
      processSearch.value = item.process_name || ''
      showModal.value = true
    }

    async function doSave() {
      if (!form.value.order_id || !form.value.process_id) { showToast('请选择订单和工序', 'error'); return }
      autoCalcQty()
      try {
        let r
        if (isEdit.value) {
          const payload = { inspection_type: form.value.inspection_type, quantity_checked: form.value.quantity_checked, quantity_passed: form.value.quantity_passed, quantity_failed: form.value.quantity_failed, defect_category: form.value.defect_category || '', defect_quantity: form.value.defect_quantity || 0, notes: form.value.notes, inspected_at: form.value.inspected_at }
          r = await api.put('/api/quality/inspections/' + form.value.id, payload)
        } else {
          r = await api.post('/api/quality/inspections', form.value)
        }
        if (r.ok) { showToast(isEdit.value ? '已更新' : '已创建'); showModal.value = false; load(page.value); loadStats() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('保存失败', 'error') }
    }

    async function doDelete(item) {
      if (!confirm('确认删除检验记录？')) return
      try {
        const r = await api.del('/api/quality/inspections/' + item.id)
        if (r.ok) { showToast('已删除'); load(page.value); loadStats() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('删除失败', 'error') }
    }

    function applyFilter() { page.value = 1; load() }

    // Pareto
    const pareto = ref({ items: [], grand_total: 0 })

    async function loadDefectCategories() {
      try {
        const r = await api.get('/api/quality/defect-categories')
        if (r.ok && r.categories) defectCategories.value = r.categories
      } catch (e) {}
    }

    async function loadPareto() {
      try {
        const params = []
        if (dateFrom.value) params.push('from=' + dateFrom.value)
        if (dateTo.value) params.push('to=' + dateTo.value)
        const r = await api.get('/api/quality/defect-pareto?' + params.join('&'))
        if (r.ok) pareto.value = r
      } catch (e) {}
    }

    onMounted(() => { load(); loadStats(); loadPareto(); loadDefectCategories(); loadProcessesCache() })

    return { items, loading, stats, search, filterType, filterResult, dateFrom, dateTo, page, total, perPage, editing,
      canEdit, canDelete, canCreate, showModal, isEdit, form, orders, processes, orderSearch, processSearch, orderDropdown, processDropdown,
      defectCategories, pareto,
      fmtDate, fmtDatetime, typeLabel, resultLabel,
      load, loadStats, loadDefectCategories, searchOrders, searchProcesses, selectOrder, selectProcess, autoCalcQty, onCheckedQtyManual, openCreate, openEdit, doSave, doDelete, applyFilter, loadPareto }
  }
}
</script>
