<!-- ReworkList.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- Stats Row -->
    <div class="summary-bar">
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--warning);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">🔧</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700;color:var(--warning)">{{ stats.pending_count }}</div><div style="font-size:var(--text-sm);color:var(--text-muted)">待处理 / {{ stats.pending_qty }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--danger);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">📋</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700;color:var(--danger)">{{ stats.today_count }}</div><div style="font-size:var(--text-sm);color:var(--text-muted)">今日新增 / {{ stats.today_qty }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--success);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">✅</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700;color:var(--success)">{{ stats.today_done }}</div><div style="font-size:var(--text-sm);color:var(--text-muted)">今日完成 / {{ stats.today_done_qty }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--primary-accent);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">📅</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700" :style="{color: stats.week_rate > 5 ? 'var(--danger)' : 'var(--primary-accent)'}">{{ stats.week_rate }}%</div><div style="font-size:var(--text-sm);color:var(--text-muted)">本周返工率 / {{ stats.week_rework_qty || 0 }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--warning);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">📆</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700" :style="{color: stats.month_rate > 5 ? 'var(--danger)' : 'var(--warning)'}">{{ stats.month_rate }}%</div><div style="font-size:var(--text-sm);color:var(--text-muted)">本月返工率 / {{ stats.month_rework_qty || 0 }} 件</div></div>
      </div>
    </div>

    <!-- Main Card -->
    <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
      <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap;padding:var(--space-3) 20px">
        <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:var(--space-2);margin:0">
          <span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--warning),var(--warning-dark));border-radius:var(--radius-md);font-size:var(--text-lg);color:white">🔧</span>
          返工管理
        </h3>
        <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto;flex-wrap:wrap">
          <button class="btn-sm" :style="{borderRadius:'8px',border:'1px solid var(--border-light)',background:statusFilter==='pending'?'var(--warning)':'var(--bg-surface)',color:statusFilter==='pending'?'#fff':'var(--text-placeholder)',padding:'6px 14px',cursor:'pointer',fontWeight:statusFilter==='pending'?'600':'400'}" @click="switchTab('pending')">待处理</button>
          <button class="btn-sm" :style="{borderRadius:'8px',border:'1px solid var(--border-light)',background:statusFilter==='completed'?'var(--success)':'var(--bg-surface)',color:statusFilter==='completed'?'#fff':'var(--text-placeholder)',padding:'6px 14px',cursor:'pointer',fontWeight:statusFilter==='completed'?'600':'400'}" @click="switchTab('completed')">已完成</button>
          <select v-model="filterWorker" class="form-input" style="width:110px;font-size:var(--text-xs);padding:6px 8px" @change="applyFilter">
            <option value="">全部工人</option>
            <option v-for="w in workers" :key="w.id" :value="w.id">{{ w.name }}</option>
          </select>
          <select v-model="filterProcess" class="form-input" style="width:100px;font-size:var(--text-xs);padding:6px 8px" @change="applyFilter">
            <option value="">全部工序</option>
            <option v-for="p in processes" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <input v-model="search" @keyup.enter="applyFilter" placeholder="搜索订单号..." class="form-input" style="margin-left:4px;width:160px;font-size:var(--text-sm);padding:6px 10px">
          <input v-model="dateFrom" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
          <span style="color:var(--text-placeholder);font-size:var(--text-xs)">至</span>
          <input v-model="dateTo" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
          <button v-if="statusFilter==='pending' && selectedIds.length && canEdit" @click="showBatchModal=true" class="btn-success btn-sm" style="padding:6px 12px;white-space:nowrap">✅ 批量完成 ({{ selectedIds.length }})</button>
          <button @click="exportData" class="btn-sm" style="background:var(--primary-light);color:var(--primary);border:1px solid var(--primary-light);padding:6px 12px;white-space:nowrap;cursor:pointer">📥 导出</button>
        </div>
      </div>

      <div v-if="loading" style="text-align:center;padding:60px;color:var(--text-placeholder)">⏳ 加载中...</div>

      <!-- Pending Table -->
      <div v-else-if="statusFilter==='pending'" style="padding:0 20px 20px">
        <div v-if="!items.length" style="text-align:center;padding:50px;color:var(--text-placeholder)">✅ 暂无待处理返工</div>
        <table v-else style="width:100%;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
            <th style="padding:var(--space-3) 4px;text-align:center;font-weight:500;width:30px">
              <input type="checkbox" @change="toggleSelectAll" :checked="allSelected">
            </th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">订单号</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">产品 / 客户</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">工序</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:70px">工人</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:55px">数量</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">原因</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:85px">时间</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:100px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="it in items" :key="it.id" :style="{borderBottom:'1px solid var(--bg-hover)',fontSize:'var(--text-sm)',transition:'background .15s',background: isOverdue(it) ? 'var(--danger-lighter, #fff0f0)' : ''}" @mouseenter="it._hover=true" @mouseleave="it._hover=false">
              <td style="padding:var(--space-3) 4px;text-align:center">
                <input type="checkbox" :checked="selectedIds.includes(it.id)" @change="toggleSelect(it.id)">
              </td>
              <td style="padding:var(--space-3) 12px">
                <div style="font-weight:600;color:var(--primary)">{{ it.order_no }}</div>
                <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.product_name }}</div>
              </td>
              <td style="padding:var(--space-3) 12px;font-size:var(--text-xs);color:var(--text-placeholder)">{{ it.customer_name }}</td>
              <td style="padding:var(--space-3) 12px;color:var(--primary-accent);font-weight:500">{{ it.process_name }}</td>
              <td style="padding:var(--space-3) 12px">{{ it.worker_name }}</td>
              <td style="padding:var(--space-3) 12px;text-align:center;font-weight:600">{{ it.quantity }}</td>
              <td style="padding:var(--space-3) 12px">
                <div v-if="editing===it.id" style="display:flex;gap:var(--space-1);align-items:center">
                  <input v-model="it.reason" class="form-input" style="width:110px;font-size:var(--text-xs);padding:var(--space-1) 6px" @keyup.enter="saveEdit(it)">
                  <button class="btn-success btn-sm" style="padding:3px 8px;font-size:var(--text-xs-alt)" @click="saveEdit(it)">保存</button>
                  <button class="btn-sm" style="padding:3px 8px;font-size:var(--text-xs-alt);background:var(--bg-hover);border:1px solid var(--border-light);border-radius:var(--radius-sm);cursor:pointer;color:var(--text-placeholder)" @click="cancelEdit">取消</button>
                </div>
                <div v-else style="display:flex;align-items:center;gap:var(--space-1)">
                  <span v-if="it.reason" style="background:var(--warning-lighter);color:var(--warning);padding:var(--space-1) 8px;border-radius:var(--radius-sm);font-size:var(--text-xs);max-width:120px;display:inline-block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ it.reason }}</span>
                  <span v-else style="color:var(--text-placeholder)">-</span>
                  <button v-if="editing!==it.id && canEdit" class="btn-icon-edit btn-icon-sm" style="font-size:var(--text-xs);flex-shrink:0;margin-left:2px" @click="startEdit(it)" title="编辑原因">✏️</button>
                </div>
              </td>
              <td style="padding:var(--space-3) 12px;text-align:center;font-size:var(--text-xs-alt)" :style="{color: isOverdue(it) ? 'var(--danger)' : 'var(--text-placeholder)'}">
                {{ fmtDate(it.created_at) }}
                <span v-if="isOverdue(it)" style="display:block;font-size:var(--text-2xs);font-weight:600;color:var(--danger);margin-top:2px">⚠ {{ overdueHours(it) }}h</span>
              </td>
              <td style="padding:var(--space-3) 12px;text-align:center">
                <button @click="openComplete(it)" v-if="canEdit" class="btn-success btn-sm" style="padding:var(--space-1) 14px">完成返工</button>
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

      <!-- Completed Table -->
      <div v-else style="padding:0 20px 20px">
        <div v-if="!items.length" style="text-align:center;padding:50px;color:var(--text-placeholder)">暂无已完成记录</div>
        <table v-else style="width:100%;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
            <th style="padding:var(--space-3) 4px;text-align:center;font-weight:500;width:30px">
              <input type="checkbox" @change="toggleSelectAll" :checked="allSelected">
            </th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">订单号</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">产品 / 客户</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">工序</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:70px">工人</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:55px">数量</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">原因</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:85px">完成人</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:70px">结果</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:70px">耗时</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:140px">完成时间</th>
          </tr></thead>
          <tbody>
            <tr v-for="it in items" :key="it.id" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm)">
              <td style="padding:var(--space-2) 12px">
                <div style="font-weight:600;color:var(--primary)">{{ it.order_no }}</div>
                <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.product_name }}</div>
              </td>
              <td style="padding:var(--space-2) 12px;font-size:var(--text-xs);color:var(--text-placeholder)">{{ it.customer_name }}</td>
              <td style="padding:var(--space-2) 12px;color:var(--primary-accent);font-weight:500">{{ it.process_name }}</td>
              <td style="padding:var(--space-2) 12px">{{ it.worker_name }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center;font-weight:600">{{ it.quantity }}</td>
              <td style="padding:var(--space-2) 12px">
                <span v-if="it.reason" style="background:var(--warning-lighter);color:var(--warning);padding:var(--space-1) 8px;border-radius:var(--radius-sm);font-size:var(--text-xs)">{{ it.reason }}</span>
                <span v-else style="color:var(--text-placeholder)">-</span>
              </td>
              <td style="padding:var(--space-2) 12px;color:var(--text-secondary)">{{ it.completed_by_name || '-' }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center">
                <span v-if="it.result==='ok'" style="color:var(--success);font-weight:600">✅ 合格</span>
                <span v-else-if="it.result==='scrap'" style="color:var(--danger);font-weight:600">❌ 报废</span>
                <span v-else-if="it.result==='rework_again'" style="color:var(--warning);font-weight:600">🔧 再返</span>
                <span v-else style="color:var(--text-placeholder)">-</span>
              </td>
              <td style="padding:var(--space-2) 12px;text-align:center;font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.duration_hours ? it.duration_hours+'h' : '-' }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center;font-size:var(--text-xs-alt);color:var(--success)">{{ fmtDatetime(it.completed_at) }}</td>
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
  </div>

    <!-- 批量完成弹窗 -->
    <div v-if="showBatchModal" class="modal-overlay" >
      <div class="modal" style="max-width:440px;width:95%">
        <div class="modal-header">
          <span>✅ 批量完成返工 ({{ selectedIds.length }} 条)</span>
          <span class="modal-close" @click="showBatchModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-group"><label>批量结果 *</label>
            <select class="form-input" v-model="batchResult">
              <option value="ok">✅ 合格</option>
              <option value="scrap">❌ 报废</option>
              <option value="rework_again">🔧 需再次返工</option>
            </select>
          </div>
          <div class="form-group"><label>批量原因（可选）</label>
            <textarea class="form-input" v-model="batchReason" rows="2" placeholder="统一返工原因..."></textarea>
          </div>
          <div style="font-size:var(--text-xs);color:var(--text-placeholder);padding:8px;background:var(--bg-hover);border-radius:8px">
            将对选中的 {{ selectedIds.length }} 条待处理返工统一标记完成
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showBatchModal=false">取消</button>
          <button class="btn btn-primary" @click="doBatchComplete">确认批量完成</button>
        </div>
      </div>
    </div>

    <!-- 完成返工弹窗 -->
    <div v-if="completingItem" class="modal-overlay" >
      <div class="modal" style="max-width:420px;width:95%">
        <div class="modal-header">
          <span>✅ 完成返工 — {{ completingItem.order_no }}</span>
          <span class="modal-close" @click="closeComplete">&times;</span>
        </div>
        <div class="modal-body">
          <div style="margin-bottom:12px;font-size:var(--text-sm)">
            <b>工序:</b> {{ completingItem.process_name }} | <b>数量:</b> {{ completingItem.quantity }} | <b>工人:</b> {{ completingItem.worker_name }}
          </div>
          <div class="form-group"><label>返工结果 *</label>
            <select class="form-input" v-model="completeResult">
              <option value="ok">✅ 合格 — 返工后通过检验</option>
              <option value="scrap">❌ 报废 — 无法修复</option>
              <option value="rework_again">🔧 需再次返工</option>
            </select>
          </div>
          <div class="form-group"><label>处理备注</label>
            <textarea class="form-input" v-model="completeResultRemark" rows="2" placeholder="返工处理说明..."></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="closeComplete">取消</button>
          <button class="btn btn-primary" @click="doComplete">确认完成</button>
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
    const statusFilter = ref('pending')
    const search = ref('')
    const filterWorker = ref('')
    const filterProcess = ref('')
    const workers = ref([])
    const processes = ref([])
    const selectedIds = ref([])
    const showBatchModal = ref(false)
    const batchReason = ref('')
    const batchResult = ref('ok')
    const stats = ref({ pending_count:0, pending_qty:0, today_count:0, today_qty:0, today_done:0, today_done_qty:0 })
    const editing = ref(null)
    const dateFrom = ref('')
    const dateTo = ref('')
    const page = ref(1)
    const total = ref(0)
    const perPage = 20

    // RBAC
    const canEdit   = computed(() => can('rework:edit'))
    const canCreate = computed(() => can('rework:create'))

    const allSelected = computed(() => {
      return items.value.length > 0 && items.value.every(it => selectedIds.value.includes(it.id))
    })

    function fmtDate(s) {
      if (!s) return ''
      const m = s.match(/^\d{4}-\d{2}-\d{2}/)
      return m ? m[0] : s
    }
    function fmtDatetime(s) {
      if (!s) return ''
      const m = s.match(/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}/)
      return m ? m[0] : s
    }
    function isOverdue(it) {
      if (!it.created_at || it.status !== 'pending') return false
      const created = new Date(it.created_at.replace(' ', 'T'))
      const now = new Date()
      return (now - created) > 24 * 60 * 60 * 1000
    }
    function overdueHours(it) {
      if (!it.created_at) return 0
      const created = new Date(it.created_at.replace(' ', 'T'))
      const now = new Date()
      return Math.round((now - created) / (60 * 60 * 1000))
    }

    async function load(p = 1) {
      loading.value = true; page.value = p
      const qs = []
      if (statusFilter.value) qs.push('status=' + statusFilter.value)
      if (search.value) qs.push('search=' + encodeURIComponent(search.value))
      if (dateFrom.value) qs.push('from=' + dateFrom.value)
      if (dateTo.value) qs.push('to=' + dateTo.value)
      qs.push('page=' + p, 'per_page=' + perPage)
      try {
        const r = await api.listRework({status: statusFilter.value || undefined, search: search.value || undefined, from: dateFrom.value || undefined, to: dateTo.value || undefined, worker_id: filterWorker.value || undefined, process_id: filterProcess.value || undefined, page: p, per_page: perPage})
        if (r.ok) { items.value = r.items; total.value = r.total }
      } catch (e) { showToast('加载失败', 'error') }
      finally { loading.value = false }
    }

    async function loadStats() {
      try { const r = await api.reworkStats(); if (r.ok) stats.value = r } catch (e) {}
    }

    const completingItem = ref(null)
    const completeResult = ref('ok')
    const completeResultRemark = ref('')

    function openComplete(item) {
      completingItem.value = item
      completeResult.value = 'ok'
      completeResultRemark.value = ''
    }
    function closeComplete() { completingItem.value = null }

    async function doComplete() {
      const item = completingItem.value
      if (!item) return
      try {
        const d = await api.completeRework(item.id, {
          reason: item.reason,
          result: completeResult.value,
          result_remark: completeResultRemark.value
        })
        if (d.ok) { showToast('返工完成'); completingItem.value = null; load(page.value); loadStats() }
        else showToast(d.error || '失败', 'error')
      } catch (e) { showToast('操作失败', 'error') }
    }

    function startEdit(item) { editing.value = item.id }
    function cancelEdit() { editing.value = null }

    async function saveEdit(item) {
      try {
        const r = await api.updateRework(item.id, { reason: item.reason })
        if (r.ok) { showToast('已更新'); editing.value = null }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('保存失败', 'error') }
    }

    function toggleSelect(id) {
      const idx = selectedIds.value.indexOf(id)
      if (idx >= 0) selectedIds.value.splice(idx, 1)
      else selectedIds.value.push(id)
    }
    function toggleSelectAll() {
      if (allSelected.value) selectedIds.value = []
      else selectedIds.value = items.value.map(it => it.id)
    }
    async function doBatchComplete() {
      if (!selectedIds.value.length) { showToast('请选择返工记录', 'error'); return }
      try {
        const d = await api.batchCompleteRework({
          ids: selectedIds.value,
          reason: batchReason.value,
          result: batchResult.value,
          result_remark: ''
        })
        if (d.ok) {
          showToast(`已完成 ${d.completed} 条返工`)
          selectedIds.value = []
          showBatchModal.value = false
          batchReason.value = ''
          await load(page.value)
          await loadStats()
        }
      } catch (e) { showToast(e.message || '操作失败', 'error') }
    }
    function exportData() {
      const qs = []
      if (statusFilter.value) qs.push('status=' + statusFilter.value)
      if (search.value) qs.push('search=' + encodeURIComponent(search.value))
      if (dateFrom.value) qs.push('from=' + dateFrom.value)
      if (dateTo.value) qs.push('to=' + dateTo.value)
      if (filterWorker.value) qs.push('worker_id=' + filterWorker.value)
      if (filterProcess.value) qs.push('process_id=' + filterProcess.value)
      window.open('/api/rework/export?' + qs.join('&'), '_blank')
    }

    async function loadDropdowns() {
      try {
        const w = await api.listUsers({limit: 200})
        workers.value = w.users || w.items || []
      } catch (e) {}
      try {
        const p = await api.listProcesses({limit: 200})
        processes.value = p.processes || p.items || []
      } catch (e) {}
    }

    function switchTab(status) { statusFilter.value = status; search.value = ''; filterWorker.value = ''; filterProcess.value = ''; selectedIds.value = []; page.value = 1; load() }
    function applyFilter() { page.value = 1; selectedIds.value = []; load() }

    onMounted(() => { loadDropdowns(); load(); loadStats() })

    return { items, loading, statusFilter, search, filterWorker, filterProcess, workers, processes, stats, editing, dateFrom, dateTo, page, total, perPage, fmtDate, fmtDatetime, isOverdue, overdueHours, load, loadStats, completingItem, completeResult, completeResultRemark, openComplete, closeComplete, doComplete, startEdit, cancelEdit, saveEdit, switchTab, applyFilter, canEdit, canCreate, selectedIds, allSelected, showBatchModal, batchReason, batchResult, toggleSelect, toggleSelectAll, doBatchComplete, exportData }
  }
}
</script>
