<!-- ApprovalPage.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- 统计卡 -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val" style="color:var(--warning)">{{ approvalTotal }}</div><div class="s-label">待审批</div></div></div>
      <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val">{{ historyTotal }}</div><div class="s-label">已处理</div></div></div>
      <div class="summary-item"><span class="s-icon">⏱</span><div><div class="s-val">{{ stats.avg_hours }}h</div><div class="s-label">平均审批</div></div></div>
      <div class="summary-item" v-if="stats.pending_over_24h > 0"><span class="s-icon">🔴</span><div><div class="s-val text-danger">{{ stats.pending_over_24h }}</div><div class="s-label">超24h未批</div></div></div>
    </div>

    <!-- Tab 切换 -->
    <div style="display:flex;gap:var(--space-1);margin-bottom:var(--space-5);border-bottom:2px solid var(--border-light)">
      <button class="tab-btn" :class="{active: activeTab==='pending'}" @click="setTab('pending')">
        ⏳ 待审批
      </button>
      <button class="tab-btn" :class="{active: activeTab==='history'}" @click="setTab('history')">
        📋 审批历史
      </button>
    </div>

    <!-- 筛选栏 -->
    <div v-if="activeTab==='pending'" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <input v-model="filterOrderNo" placeholder="订单号..." style="padding:5px 10px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px;width:140px">
      <input v-model="filterWorker" placeholder="工人..." style="padding:5px 10px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px;width:100px">
      <input v-model="filterProcess" placeholder="工序..." style="padding:5px 10px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px;width:120px">
      <span style="font-size:12px;color:var(--text-placeholder);line-height:30px">当前页筛选 {{ filteredApprovals.length }} / {{ approvals.length }}，共 {{ approvalTotal }} 条</span>
    </div>

    <!-- 待审批列表 -->
    <div v-if="activeTab==='pending'">
      <div v-if="loading" style="text-align:center;padding:80px;color:var(--text-placeholder)">⏳ 加载中...</div>
      <div v-else-if="approvals.length === 0" style="text-align:center;padding:80px;color:var(--text-placeholder)">
        <p style="font-size:48px;margin:0">📋</p>
        <p style="margin-top:12px">暂无待审批记录</p>
      </div>
      <div v-if="canApprove && approvals.length > 0 && filteredApprovals.length > 0" style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
        <label style="font-size:12px;cursor:pointer"><input type="checkbox" v-model="selectAll" @change="toggleSelectAll" style="margin-right:4px">全选</label>
        <span style="font-size:12px;color:var(--text-placeholder)">已选 {{ selectedIds.length }}</span>
        <button class="btn btn-success btn-sm" @click="batchHandle('approve')" :disabled="selectedIds.length===0">✅ 批量通过</button>
        <button class="btn btn-sm" style="background:var(--danger-light);color:var(--danger);border:1px solid var(--danger-lighter)" @click="batchHandle('reject')" :disabled="selectedIds.length===0">❌ 批量拒绝</button>
      </div>
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th v-if="canApprove" style="width:40px">选</th>
              <th>订单号</th>
              <th>工序</th>
              <th>工人</th>
              <th>数量</th>
              <th>报工信息</th>
              <th>级别</th>
              <th>提交时间</th>
              <th v-if="canApprove">拒绝原因</th>
              <th v-if="canApprove" style="width:200px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in filteredApprovals" :key="a.id">
              <td v-if="canApprove"><input type="checkbox" :value="a.id" v-model="selectedIds" style="cursor:pointer"></td>
              <td><span style="font-weight:600;color:var(--primary)">{{ a.order_no || '-' }}</span></td>
              <td>{{ a.process_name || '-' }}</td>
              <td>{{ a.worker_name || '-' }}</td>
              <td>{{ a.quantity }}</td>
              <td class="approval-detail">
                <span class="report-source-badge" :class="{ backfill: a.report_source === 'serial_backfill' }">
                  {{ a.report_source === 'serial_backfill' ? '序列号补报' : '正常报工' }}
                </span>
                <template v-if="a.report_source === 'serial_backfill'">
                  <div>序列号：{{ a.serial_no || '-' }}</div>
                  <div>提交岗位：{{ a.submit_position_name || '-' }}</div>
                  <template v-if="a.actual_completed_at || a.backfill_reason">
                    <div>实际完成：{{ a.actual_completed_at || '-' }}</div>
                    <div class="backfill-reason">原因：{{ a.backfill_reason || '-' }}</div>
                  </template>
                </template>
              </td>
              <td><span style="font-size:11px;background:var(--primary-light);color:var(--primary);padding:1px 6px;border-radius:8px">L{{ a.current_level || 1 }}</span></td>
              <td style="font-size:var(--text-sm);color:var(--text-placeholder)">{{ a.created_at }}</td>
              <td v-if="canApprove" class="approval-actions">
                <input class="form-input" v-model="rejectComment[a.id]" placeholder="拒绝原因(可选)" style="font-size:var(--text-xs);padding:var(--space-1) 8px;width:120px" @keyup.enter="handle(a.id,'reject')">
              </td>
              <td v-if="canApprove">
                <button class="btn btn-success btn-sm" @click="handle(a.id, 'approve')" :disabled="processing[a.id]" style="margin-right:8px">
                  {{ processing[a.id] ? '处理中...' : '✅ 通过' }}
                </button>
                <button class="btn btn-sm" style="background:var(--danger-light);color:var(--danger);border:1px solid var(--danger-lighter)" @click="handle(a.id, 'reject')" :disabled="processing[a.id]">
                  {{ processing[a.id] ? '处理中...' : '❌ 拒绝' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="approvalTotal > approvalLimit" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0">
        <button class="btn btn-default btn-sm" @click="changeApprovalPage(-1)" :disabled="loading || approvalPage <= 1">上一页</button>
        <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ approvalPage }} / {{ Math.ceil(approvalTotal / approvalLimit) }} 页</span>
        <button class="btn btn-default btn-sm" @click="changeApprovalPage(1)" :disabled="loading || approvalPage * approvalLimit >= approvalTotal">下一页</button>
      </div>
    </div>

    <!-- 审批历史列表 -->
    <div v-if="activeTab==='history'">
      <div v-if="historyLoading" style="text-align:center;padding:80px;color:var(--text-placeholder)">⏳ 加载中...</div>
      <div v-else-if="history.length === 0" style="text-align:center;padding:80px;color:var(--text-placeholder)">
        <p style="font-size:48px;margin:0">📋</p>
        <p style="margin-top:12px">暂无审批记录</p>
      </div>
      <div v-else class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>工序</th>
              <th>工人</th>
              <th>数量</th>
              <th>报工信息</th>
              <th>状态</th>
              <th>审批人</th>
              <th>备注</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in history" :key="a.id">
              <td><span style="font-weight:600;color:var(--primary)">{{ a.order_no || '-' }}</span></td>
              <td>{{ a.process_name || '-' }}</td>
              <td>{{ a.worker_name || '-' }}</td>
              <td>{{ a.quantity }}</td>
              <td class="approval-detail">
                <span class="report-source-badge" :class="{ backfill: a.report_source === 'serial_backfill' }">
                  {{ a.report_source === 'serial_backfill' ? '序列号补报' : '正常报工' }}
                </span>
                <template v-if="a.report_source === 'serial_backfill'">
                  <div>序列号：{{ a.serial_no || '-' }}</div>
                  <div>提交岗位：{{ a.submit_position_name || '-' }}</div>
                  <template v-if="a.actual_completed_at || a.backfill_reason">
                    <div>实际完成：{{ a.actual_completed_at || '-' }}</div>
                    <div class="backfill-reason">原因：{{ a.backfill_reason || '-' }}</div>
                  </template>
                </template>
              </td>
              <td>
                <span class="badge" :class="a.status==='approved'?'badge-success':'badge-danger'" style="font-size:var(--text-xs-alt)">
                  {{ a.status==='approved'?'已批准':'已拒绝' }}
                </span>
              </td>
              <td>{{ a.approver_name || '-' }}</td>
              <td style="font-size:var(--text-xs);color:var(--text-placeholder);max-width:150px">{{ a.comment || '-' }}</td>
              <td style="font-size:var(--text-sm);color:var(--text-placeholder)">{{ a.processed_at || a.created_at }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="historyTotal > 20" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0">
          <button class="btn btn-default btn-sm" @click="historyPage--;loadHistory()" :disabled="historyPage <= 1">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ historyPage }} / {{ Math.ceil(historyTotal/20) }} 页</span>
          <button class="btn btn-default btn-sm" @click="historyPage++;loadHistory()" :disabled="historyPage * 20 >= historyTotal">下一页</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export default {
  setup() {
    const approvals = ref([])
    const approvalTotal = ref(0)
    const approvalPage = ref(1)
    const approvalLimit = 20
    const loading = ref(true)
    const filterOrderNo = ref('')
    const filterWorker = ref('')
    const filterProcess = ref('')
    const selectedIds = ref([])
    const selectAll = ref(false)
    const processing = ref({})
    const activeTab = ref('pending')  // 'pending' | 'history'
    const stats = ref({ pending: 0, avg_hours: 0, pending_over_24h: 0, total: 0 })
    const history = ref([])
    const historyTotal = ref(0)
    const historyPage = ref(1)
    const historyLoading = ref(false)
    const rejectComment = ref({})  // { [id]: comment }

    const canApprove = computed(() => can('approvals:decision'))
    const filteredApprovals = computed(() => {
      let arr = approvals.value
      if (filterOrderNo.value) {
        const q = filterOrderNo.value.toLowerCase()
        arr = arr.filter(a => (a.order_no || '').toLowerCase().includes(q))
      }
      if (filterWorker.value) {
        const q = filterWorker.value.toLowerCase()
        arr = arr.filter(a => (a.worker_name || '').toLowerCase().includes(q))
      }
      if (filterProcess.value) {
        const q = filterProcess.value.toLowerCase()
        arr = arr.filter(a => (a.process_name || '').toLowerCase().includes(q))
      }
      return arr
    })

    async function load(page = approvalPage.value) {
      loading.value = true
      selectedIds.value = []
      selectAll.value = false
      try {
        const d = await api.domains.approvals.pendingApprovals({ page, limit: approvalLimit })
        approvalPage.value = d.page || page
        approvals.value = d.approvals || []
        approvalTotal.value = d.total || 0
      } catch(e) { showToast(e.message || '加载失败', 'error') }
      finally { loading.value = false }
    }

    function changeApprovalPage(offset) {
      const nextPage = approvalPage.value + offset
      const maxPage = Math.max(1, Math.ceil(approvalTotal.value / approvalLimit))
      if (nextPage < 1 || nextPage > maxPage) return
      load(nextPage)
    }

    async function loadHistory() {
      historyLoading.value = true
      try {
        const d = await api.domains.approvals.approvalHistory({ page: historyPage.value })
        history.value = d.approvals || []
        historyTotal.value = d.total || 0
      } catch(e) { showToast(e.message || '加载失败', 'error') }
      finally { historyLoading.value = false }
    }

    function toggleSelectAll() {
      if (selectAll.value) {
        selectedIds.value = filteredApprovals.value.map(a => a.id)
      } else {
        selectedIds.value = []
      }
    }

    // 筛选条件变化时清空已选项，防止误操作不可见记录
    watch([filterOrderNo, filterWorker, filterProcess], () => {
      selectedIds.value = []
      selectAll.value = false
    })

    async function batchHandle(action) {
      if (selectedIds.value.length === 0) return
      const label = action === 'approve' ? '通过' : '拒绝'
      if (!confirm('确定批量' + label + ' ' + selectedIds.value.length + ' 条审批？')) return
      try {
        const result = await api.domains.approvals.batchApproval(selectedIds.value, action)
        if (result.failed && result.failed.length > 0) {
          showToast(result.message + '，' + result.failed.length + ' 条失败', 'warning')
        } else {
          showToast('已批量' + label)
        }
        selectedIds.value = []
        selectAll.value = false
        await Promise.all([load(), loadStats()])
      } catch(e) { showToast(e.message || '操作失败', 'error') }
    }

    function setTab(tab) {
      activeTab.value = tab
      if (tab === 'history') loadHistory()
    }

    async function loadStats() {
      try {
        const d = await api.domains.approvals.approvalStats()
        stats.value = d
      } catch(e) { console.warn('Approval stats load failed:', e) }
    }

    async function handle(id, action) {
      if (!canApprove.value) return
      processing.value[id] = true
      try {
        const comment = action === 'reject' ? (rejectComment.value[id] || '') : ''
        await api.domains.approvals.handleApproval(id, action, comment)
        showToast(action === 'approve' ? '已批准' : '已拒绝')
        delete rejectComment.value[id]
        await Promise.all([load(), loadStats()])
      } catch(e) { showToast(e.message || '操作失败', 'error') }
      finally { processing.value[id] = false }
    }

    onMounted(() => { load(); loadStats() })

    return {
      approvals, approvalTotal, approvalPage, approvalLimit, loading, processing, canApprove, filteredApprovals,
      filterOrderNo, filterWorker, filterProcess,
      activeTab, setTab, history, historyTotal, historyPage, historyLoading, loadHistory,
      rejectComment, handle, selectedIds, selectAll, toggleSelectAll, batchHandle,
      stats, changeApprovalPage
    }
  }
}
</script>

<style scoped>
.approval-actions {
  white-space: nowrap;
}

.approval-detail {
  font-size: var(--text-xs);
  line-height: 1.6;
  min-width: 190px;
}

.report-source-badge {
  background: var(--bg-hover);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  display: inline-block;
  margin-bottom: var(--space-1);
  padding: 2px 7px;
}

.report-source-badge.backfill {
  background: var(--warning-light);
  color: var(--warning-dark);
}

.backfill-reason {
  max-width: 260px;
  white-space: normal;
}
</style>
