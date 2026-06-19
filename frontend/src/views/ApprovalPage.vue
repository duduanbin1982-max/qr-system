<!-- ApprovalPage.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- 统计卡 -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val" style="color:var(--warning)">{{ approvals.length }}</div><div class="s-label">待审批</div></div></div>
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
      <button class="tab-btn" :class="{active: activeTab==='config'}" @click="setTab('config')" v-if="canApprove">
        ⚙️ 审批配置
      </button>
    </div>

    <!-- 筛选栏 -->
    <div v-if="activeTab==='pending'" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <input v-model="filterOrderNo" placeholder="订单号..." style="padding:5px 10px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px;width:140px">
      <input v-model="filterWorker" placeholder="工人..." style="padding:5px 10px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px;width:100px">
      <input v-model="filterProcess" placeholder="工序..." style="padding:5px 10px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px;width:120px">
      <span style="font-size:12px;color:var(--text-placeholder);line-height:30px">筛选 {{ filteredApprovals.length }} / {{ approvals.length }}</span>
    </div>

    <!-- 待审批列表 -->
    <div v-if="activeTab==='pending'">
      <div v-if="loading" style="text-align:center;padding:80px;color:var(--text-placeholder)">⏳ 加载中...</div>
      <div v-else-if="approvals.length === 0" style="text-align:center;padding:80px;color:var(--text-placeholder)">
        <p style="font-size:48px;margin:0">📋</p>
        <p style="margin-top:12px">暂无待审批记录</p>
      </div>
      <div v-if="approvals.length > 0 && filteredApprovals.length > 0" style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
        <label style="font-size:12px;cursor:pointer"><input type="checkbox" v-model="selectAll" @change="toggleSelectAll" style="margin-right:4px">全选</label>
        <span style="font-size:12px;color:var(--text-placeholder)">已选 {{ selectedIds.length }}</span>
        <button class="btn btn-success btn-sm" @click="batchHandle('approve')" :disabled="selectedIds.length===0">✅ 批量通过</button>
        <button class="btn btn-sm" style="background:var(--danger-light);color:var(--danger);border:1px solid var(--danger-lighter)" @click="batchHandle('reject')" :disabled="selectedIds.length===0">❌ 批量拒绝</button>
      </div>
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width:40px">选</th>
              <th>订单号</th>
              <th>工序</th>
              <th>工人</th>
              <th>数量</th>
              <th>级别</th>
              <th>提交时间</th>
              <th v-if="canApprove">拒绝原因</th>
              <th v-if="canApprove" style="width:200px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in filteredApprovals" :key="a.id">
              <td><input type="checkbox" :value="a.id" v-model="selectedIds" style="cursor:pointer"></td>
              <td><span style="font-weight:600;color:var(--primary)">{{ a.order_no || '-' }}</span></td>
              <td>{{ a.process_name || '-' }}</td>
              <td>{{ a.worker_name || '-' }}</td>
              <td>{{ a.quantity }}</td>
              <td><span style="font-size:11px;background:var(--primary-light);color:var(--primary);padding:1px 6px;border-radius:8px">L{{ a.current_level || 1 }}</span></td>
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

    <!-- 审批配置 -->
    <div v-if="activeTab==='config'">
      <div class="card">
        <div class="card-header"><h3>⚙️ 工序审批配置</h3></div>
        <div class="card-body">
          <table class="data-table" v-if="configProcesses.length">
            <thead><tr><th>工序名称</th><th>分类</th><th>需审批</th><th>一级审批</th><th>二级审批</th><th>三级审批</th></tr></thead>
            <tbody>
              <tr v-for="p in configProcesses" :key="p.id">
                <td style="font-weight:500">{{ p.name }}</td>
                <td style="color:var(--text-placeholder);font-size:12px">{{ p.category || '-' }}</td>
                <td>
                  <input type="checkbox" v-model="p.require_approval" :true-value="1" :false-value="0" @change="saveConfig(p)" style="accent-color:var(--primary);cursor:pointer">
                </td>
                <td>
                  <select v-model="p.approver_role" @change="saveConfig(p)" style="padding:4px 8px;border:1px solid #d9d9d9;border-radius:4px;font-size:12px">
                    <option value="admin">管理员</option>
                    <option value="supervisor">主管</option>
                    <option value="quality">质检员</option>
                  </select>
                </td>
                <td>
                  <select v-model="p.approver_role_2" @change="saveConfig(p)" style="padding:4px 8px;border:1px solid #d9d9d9;border-radius:4px;font-size:12px">
                    <option value="">-- 无 --</option>
                    <option value="admin">管理员</option>
                    <option value="supervisor">主管</option>
                    <option value="quality">质检员</option>
                  </select>
                </td>
                <td>
                  <select v-model="p.approver_role_3" @change="saveConfig(p)" style="padding:4px 8px;border:1px solid #d9d9d9;border-radius:4px;font-size:12px">
                    <option value="">-- 无 --</option>
                    <option value="admin">管理员</option>
                    <option value="supervisor">主管</option>
                    <option value="quality">质检员</option>
                  </select>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;padding:40px;color:var(--text-placeholder)">暂无工序数据</p>
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
    const filterOrderNo = ref('')
    const filterWorker = ref('')
    const filterProcess = ref('')
    const selectedIds = ref([])
    const selectAll = ref(false)
    const processing = ref({})
    const activeTab = ref('pending')  // 'pending' | 'history' | 'config'
    const stats = ref({ pending: 0, avg_hours: 0, pending_over_24h: 0, total: 0 })
    const configProcesses = ref([])
    const history = ref([])
    const historyTotal = ref(0)
    const historyPage = ref(1)
    const historyLoading = ref(false)
    const rejectComment = ref({})  // { [id]: comment }

    const canApprove = computed(() => can('approvals:edit'))
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

    function toggleSelectAll() {
      if (selectAll.value) {
        selectedIds.value = filteredApprovals.value.map(a => a.id)
      } else {
        selectedIds.value = []
      }
    }

    async function batchHandle(action) {
      if (selectedIds.value.length === 0) return
      const label = action === 'approve' ? '通过' : '拒绝'
      if (!confirm('确定批量' + label + ' ' + selectedIds.value.length + ' 条审批？')) return
      try {
        const result = await api.batchApproval(selectedIds.value, action)
        if (result.failed && result.failed.length > 0) {
          showToast(result.message + '，' + result.failed.length + ' 条失败', 'warning')
        } else {
          showToast('已批量' + label)
        }
        selectedIds.value = []
        selectAll.value = false
        await load()
      } catch(e) { showToast(e.message || '操作失败', 'error') }
    }

    function setTab(tab) {
      activeTab.value = tab
      if (tab === 'history') loadHistory()
      if (tab === 'config') loadConfig()
    }

    async function loadStats() {
      try {
        const d = await api.approvalStats()
        stats.value = d
      } catch(e) {}
    }

    async function loadConfig() {
      try {
        const d = await api.approvalConfig()
        configProcesses.value = d.configs || []
      } catch(e) { showToast('加载配置失败', 'error') }
    }

    async function saveConfig(p) {
      try {
        const level = p.approver_role_3 ? 3 : (p.approver_role_2 ? 2 : 1)
        await api.saveApprovalConfig({
          process_id: p.process_id || p.id,
          require_approval: p.require_approval,
          approver_role: p.approver_role || 'admin',
          approver_role_2: p.approver_role_2 || '',
          approver_role_3: p.approver_role_3 || '',
          approval_level: level
        })
      } catch(e) { showToast('保存失败', 'error') }
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

    onMounted(() => { load(); loadStats() })

    return {
      approvals, loading, processing, canApprove, filteredApprovals,
      filterOrderNo, filterWorker, filterProcess,
      activeTab, setTab, history, historyTotal, historyPage, historyLoading, loadHistory,
      rejectComment, handle, selectedIds, selectAll, toggleSelectAll, batchHandle,
      stats, configProcesses, loadConfig, saveConfig
    }
  }
}
</script>
