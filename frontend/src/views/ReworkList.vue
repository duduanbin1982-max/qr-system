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
          <input v-model="search" @keyup.enter="applyFilter" placeholder="搜索订单号/工序..." class="form-input" style="margin-left:4px;width:180px;font-size:var(--text-sm);padding:6px 10px">
          <input v-model="dateFrom" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
          <span style="color:var(--text-placeholder);font-size:var(--text-xs)">至</span>
          <input v-model="dateTo" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
        </div>
      </div>

      <div v-if="loading" style="text-align:center;padding:60px;color:var(--text-placeholder)">⏳ 加载中...</div>

      <!-- Pending Table -->
      <div v-else-if="statusFilter==='pending'" style="padding:0 20px 20px">
        <div v-if="!items.length" style="text-align:center;padding:50px;color:var(--text-placeholder)">✅ 暂无待处理返工</div>
        <table v-else style="width:100%;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
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
            <tr v-for="it in items" :key="it.id" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm);transition:background .15s" @mouseenter="it._hover=true" @mouseleave="it._hover=false">
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
              <td style="padding:var(--space-3) 12px;text-align:center;font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ fmtDate(it.created_at) }}</td>
              <td style="padding:var(--space-3) 12px;text-align:center">
                <button @click="complete(it)" v-if="canEdit" class="btn-success btn-sm" style="padding:var(--space-1) 14px">完成返工</button>
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
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">订单号</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">产品 / 客户</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">工序</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:70px">工人</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:55px">数量</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">原因</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:85px">完成人</th>
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
    const stats = ref({ pending_count:0, pending_qty:0, today_count:0, today_qty:0, today_done:0, today_done_qty:0 })
    const editing = ref(null)
    const dateFrom = ref('')
    const dateTo = ref('')
    const page = ref(1)
    const total = ref(0)
    const perPage = 20

    // RBAC
    const canEdit   = computed(() => can('rework:edit'))

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

    async function load(p = 1) {
      loading.value = true; page.value = p
      const params = []
      if (statusFilter.value) params.push('status=' + statusFilter.value)
      if (search.value) params.push('search=' + encodeURIComponent(search.value))
      if (dateFrom.value) params.push('from=' + dateFrom.value)
      if (dateTo.value) params.push('to=' + dateTo.value)
      params.push('page=' + p, 'per_page=' + perPage)
      try {
        const r = await api.get('/api/rework?' + params.join('&'))
        if (r.ok) { items.value = r.items; total.value = r.total }
      } catch (e) { showToast('加载失败', 'error') }
      finally { loading.value = false }
    }

    async function loadStats() {
      try { const r = await api.get('/api/rework/stats'); if (r.ok) stats.value = r } catch (e) {}
    }

    async function complete(item) {
      if (!confirm('确认完成返工 ' + item.order_no + '？')) return
      try {
        const r = await api.post('/api/rework/' + item.id + '/complete', { reason: item.reason })
        if (r.ok) { showToast('返工完成'); load(page.value); loadStats() }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('操作失败', 'error') }
    }

    function startEdit(item) { editing.value = item.id }
    function cancelEdit() { editing.value = null }

    async function saveEdit(item) {
      try {
        const r = await api.put('/api/rework/' + item.id, { reason: item.reason })
        if (r.ok) { showToast('已更新'); editing.value = null }
        else showToast(r.error || '失败', 'error')
      } catch (e) { showToast('保存失败', 'error') }
    }

    function switchTab(status) { statusFilter.value = status; search.value = ''; page.value = 1; load() }
    function applyFilter() { page.value = 1; load() }

    onMounted(() => { load(); loadStats() })

    return { items, loading, statusFilter, search, stats, editing, dateFrom, dateTo, page, total, perPage, fmtDate, fmtDatetime, load, loadStats, complete, startEdit, cancelEdit, saveEdit, switchTab, applyFilter, canEdit }
  }
}
</script>
