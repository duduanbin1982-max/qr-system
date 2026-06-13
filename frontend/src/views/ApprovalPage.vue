<!-- ApprovalPage.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- 统计卡 -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val" style="color:var(--warning)">{{ approvals.length }}</div><div class="s-label">待审批</div></div></div>
      <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val">{{ historyTotal }}</div><div class="s-label">已处理</div></div></div>
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

    <!-- 待审批列表 -->
    <div v-if="activeTab==='pending'">
      <div v-if="loading" style="text-align:center;padding:80px;color:var(--text-placeholder)">⏳ 加载中...</div>
      <div v-else-if="approvals.length === 0" style="text-align:center;padding:80px;color:var(--text-placeholder)">
        <p style="font-size:48px;margin:0">📋</p>
        <p style="margin-top:12px">暂无待审批记录</p>
      </div>
      <div v-else class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>工序</th>
              <th>工人</th>
              <th>数量</th>
              <th>提交时间</th>
              <th v-if="canApprove">拒绝原因</th>
              <th v-if="canApprove" style="width:200px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in approvals" :key="a.id">
              <td><span style="font-weight:600;color:var(--primary)">{{ a.order_no || '-' }}</span></td>
              <td>{{ a.process_name || '-' }}</td>
              <td>{{ a.worker_name || '-' }}</td>
              <td>{{ a.quantity }}</td>
              <td style="font-size:var(--text-sm);color:var(--text-placeholder)">{{ a.created_at }}</td>
              <td v-if="canApprove">
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
              <td>
                <span class="badge" :class="a.status==='approved'?'badge-success':'badge-danger'" style="font-size:var(--text-xs-alt)">
                  {{ a.status==='approved'?'已批准':'已拒绝' }}
                </span>
              </td>
              <td>{{ a.approver_name || '-' }}</td>
              <td style="font-size:var(--text-xs);color:var(--text-placeholder);max-width:150px">{{ a.comment || '-' }}</td>
              <td style="font-size:var(--text-sm);color:var(--text-placeholder)">{{ a.created_at }}</td>
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
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export default {
  setup() {
    const approvals = ref([])
    const loading = ref(true)
    const processing = ref({})
    const activeTab = ref('pending')  // 'pending' | 'history'
    const history = ref([])
    const historyTotal = ref(0)
    const historyPage = ref(1)
    const historyLoading = ref(false)
    const rejectComment = ref({})  // { [id]: comment }

    const canApprove = computed(() => can('approvals:edit'))

    async function load() {
      loading.value = true
      try {
        const d = await api.pendingApprovals()
        approvals.value = d.approvals || []
      } catch(e) { showToast(e.message || '加载失败', 'error') }
      finally { loading.value = false }
    }

    async function loadHistory() {
      historyLoading.value = true
      try {
        const d = await api.approvalHistory({ page: historyPage.value })
        history.value = d.approvals || []
        historyTotal.value = d.total || 0
      } catch(e) { showToast(e.message || '加载失败', 'error') }
      finally { historyLoading.value = false }
    }

    function setTab(tab) {
      activeTab.value = tab
      if (tab === 'history') loadHistory()  // 每次切换都刷新
    }

    async function handle(id, action) {
      if (!canApprove.value) return
      processing.value[id] = true
      try {
        const comment = action === 'reject' ? (rejectComment.value[id] || '') : ''
        await api.handleApproval(id, action, comment)
        showToast(action === 'approve' ? '已批准' : '已拒绝')
        delete rejectComment.value[id]
        await load()
      } catch(e) { showToast(e.message || '操作失败', 'error') }
      finally { processing.value[id] = false }
    }

    onMounted(() => load())

    return {
      approvals, loading, processing, canApprove,
      activeTab, setTab, history, historyTotal, historyPage, historyLoading, loadHistory,
      rejectComment, handle
    }
  }
}
</script>
