<template>
  <div class="pqe-page">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val">{{ taskTotal }}</div><div class="s-label">待评价</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val">{{ statsSummary.total || 0 }}</div><div class="s-label">评价总数</div></div></div>
      <div class="summary-item"><span class="s-icon">📊</span><div><div class="s-val text-primary">{{ statsSummary.avg_score || 0 }}</div><div class="s-label">平均分</div></div></div>
      <div class="summary-item"><span class="s-icon">⚠️</span><div><div class="s-val text-warning">{{ statsSummary.pending_verification || 0 }}</div><div class="s-label">待核验</div></div></div>
      <div class="summary-item"><span class="s-icon">🔎</span><div><div class="s-val text-danger">{{ statsSummary.low_score_count || 0 }}</div><div class="s-label">低分记录</div></div></div>
    </div>

    <div class="card">
      <div class="card-header pqe-toolbar">
        <div>
          <h3>工序质量评价</h3>
          <div class="pqe-subtitle">下道工序评价同一工件全部已完成上游工序</div>
        </div>
        <div class="pqe-tabs">
          <button v-for="tab in visibleTabs" :key="tab.key" class="tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
            {{ tab.label }}
            <span v-if="tab.key === 'review' && statsSummary.pending_verification" class="pqe-count">{{ statsSummary.pending_verification }}</span>
          </button>
        </div>
        <div v-if="activeTab !== 'rules'" class="pqe-filters">
          <input v-if="activeTab !== 'tasks'" v-model="yearMonth" class="form-input" type="month" @change="loadActive">
          <input v-if="activeTab !== 'stats'" v-model="keyword" class="form-input pqe-search" placeholder="搜索订单、产品、序列号或工序" @keyup.enter="loadActive">
          <button class="btn btn-default btn-sm" @click="loadActive">刷新</button>
        </div>
      </div>

      <div class="card-body">
        <section v-if="activeTab === 'tasks'" class="pqe-section">
          <div class="pqe-note">待评价任务由正常报工最终审批通过后自动生成。直接上一道工序为必评，其余已完成上游工序为选评。</div>
          <div class="table-wrap">
            <table v-if="tasks.length" class="data-table pqe-table">
              <thead><tr><th>生成时间</th><th>订单/工件</th><th>产品</th><th>待评价工序</th><th>被评价人</th><th>评价人/接手工序</th><th>要求</th><th>归属</th></tr></thead>
              <tbody>
                <tr v-for="task in tasks" :key="task.id">
                  <td>{{ task.created_at }}</td>
                  <td><code>{{ task.order_no }}</code><div class="cell-muted">{{ task.serial_no || '订单模式' }}</div></td>
                  <td>{{ task.product_name }}<div class="cell-muted">{{ task.product_code || '-' }}</div></td>
                  <td>{{ task.target_process_name }}</td>
                  <td>{{ task.target_user_name || '工序整体' }}</td>
                  <td>{{ task.evaluator_name }}<div class="cell-muted">{{ task.evaluator_process_name }}</div></td>
                  <td><span class="badge" :class="task.is_required ? 'badge-warning' : 'badge-info'">{{ task.is_required ? '必评' : '选评' }}</span></td>
                  <td>{{ task.attribution_type === 'worker' ? '个人绩效' : '工序统计' }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty"><div class="empty-icon">✅</div><div class="empty-text">暂无待评价任务</div></div>
          </div>
        </section>

        <section v-else-if="activeTab === 'records' || activeTab === 'review'" class="pqe-section">
          <div class="table-wrap">
            <table v-if="records.length" class="data-table pqe-table">
              <thead><tr><th>评价时间</th><th>订单/工件</th><th>上游工序/人员</th><th>接手工序/评价人</th><th>五维评分</th><th>总分</th><th>问题</th><th>状态</th><th v-if="activeTab === 'review'">操作</th></tr></thead>
              <tbody>
                <tr v-for="row in records" :key="row.id">
                  <td>{{ row.created_at }}</td>
                  <td><code>{{ row.order_no }}</code><div class="cell-muted">{{ row.serial_no || '订单模式' }}</div></td>
                  <td>{{ row.target_process_name }}<div class="cell-muted">{{ row.target_user_name || '工序整体' }}</div></td>
                  <td>{{ row.evaluator_process_name }}<div class="cell-muted">{{ row.evaluator_name }}</div></td>
                  <td class="dimension-cell">
                    加工{{ row.processing_quality }} / 精度{{ row.dimensional_accuracy }} / 外观{{ row.appearance_quality }}<br>
                    接续{{ row.process_continuity }} / 防护{{ row.cleanliness_protection }}
                  </td>
                  <td><strong :class="scoreClass(row.total_score)">{{ row.total_score }}</strong><div class="cell-muted">{{ row.grade }}</div></td>
                  <td>{{ issueText(row) }}</td>
                  <td><span class="badge" :class="statusClass(row.status)">{{ statusText(row.status) }}</span></td>
                  <td v-if="activeTab === 'review'" class="action-cell">
                    <button v-if="canReview" class="btn btn-success btn-sm" @click="reviewRow(row, 'confirmed')">确认</button>
                    <button v-if="canReview" class="btn btn-default btn-sm" @click="reviewRow(row, 'rejected')">驳回</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty"><div class="empty-icon">📋</div><div class="empty-text">暂无评价记录</div></div>
          </div>
        </section>

        <section v-else-if="activeTab === 'stats'" class="pqe-section">
          <div class="pqe-note">仅已确认且明确归属个人的评价进入个人绩效；订单模式多人参与的工序整体评价只进入工序统计。</div>
          <div class="table-wrap">
            <table v-if="processStats.length" class="data-table">
              <thead><tr><th>工序</th><th>评价次数</th><th>平均分</th><th>低分次数</th><th>质量状态</th></tr></thead>
              <tbody><tr v-for="row in processStats" :key="row.process_id">
                <td>{{ row.process_name }}</td><td>{{ row.evaluation_count }}</td>
                <td><strong :class="scoreClass(row.avg_score)">{{ row.avg_score }}</strong></td>
                <td>{{ row.low_score_count }}</td>
                <td><span class="badge" :class="row.avg_score >= 80 ? 'badge-success' : row.avg_score >= 60 ? 'badge-warning' : 'badge-danger'">{{ row.avg_score >= 80 ? '稳定' : row.avg_score >= 60 ? '关注' : '需改进' }}</span></td>
              </tr></tbody>
            </table>
            <div v-else class="empty"><div class="empty-icon">📊</div><div class="empty-text">暂无统计数据</div></div>
          </div>
        </section>

        <section v-else class="pqe-rules">
          <div class="form-group pqe-rule-row"><label>评价任务</label><label class="switch-label"><input v-model="ruleForm.enabled" type="checkbox"> 启用全流程工序质量评价</label></div>
          <div class="form-group pqe-rule-row"><label>直接上一道工序</label><label class="switch-label"><input v-model="ruleForm.required_previous_process" type="checkbox"> 标记为必评</label></div>
          <div class="form-group pqe-rule-row"><label>低分核验阈值</label><div class="rule-input"><input v-model.number="ruleForm.low_score_threshold" class="form-input" type="number" min="0" max="100"><span>分以下进入质量核验</span></div></div>
          <div class="form-group pqe-rule-row"><label>问题标签</label><textarea v-model="issueTagsText" class="form-input" rows="3" placeholder="用逗号分隔"></textarea></div>
          <div class="pqe-dimensions"><strong>固定评分维度</strong><span v-for="dimension in ruleForm.dimensions || []" :key="dimension.key">{{ dimension.label }}（1-5分）</span></div>
          <button v-if="canRules" class="btn btn-primary" @click="saveRules">保存评价规则</button>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const tabs = [
  { key: 'tasks', label: '待评价' },
  { key: 'records', label: '评价记录' },
  { key: 'review', label: '质量核验', permission: 'process_quality_evaluation:review' },
  { key: 'stats', label: '统计分析', permission: 'process_quality_evaluation:stats' },
  { key: 'rules', label: '评价规则', permission: 'process_quality_evaluation:rules' },
]
const visibleTabs = computed(() => tabs.filter(tab => !tab.permission || can(tab.permission)))
const activeTab = ref(localStorage.getItem('processQualityEvaluationTab') || 'tasks')
const yearMonth = ref(new Date().toISOString().slice(0, 7))
const keyword = ref('')
const tasks = ref([])
const records = ref([])
const taskTotal = ref(0)
const statsSummary = ref({})
const processStats = ref([])
const ruleForm = reactive({ enabled: true, required_previous_process: true, low_score_threshold: 60, dimensions: [] })
const issueTagsText = ref('')
const canReview = computed(() => can('process_quality_evaluation:review'))
const canRules = computed(() => can('process_quality_evaluation:rules'))

async function loadTasks() {
  const result = await api.domains.processQualityEvaluations.qualityEvaluationTasks({ scope: 'all', status: 'pending', keyword: keyword.value, per_page: 500 })
  tasks.value = result.items || []
  taskTotal.value = result.total || 0
}

async function loadRecords(status = '') {
  const result = await api.domains.processQualityEvaluations.qualityEvaluationRecords({ year_month: yearMonth.value, status, keyword: keyword.value, per_page: 500 })
  records.value = result.items || []
}

async function loadStats() {
  const result = await api.domains.processQualityEvaluations.qualityEvaluationStats({ year_month: yearMonth.value })
  statsSummary.value = result.summary || {}
  processStats.value = result.processes || []
}

async function loadRules() {
  const result = await api.domains.processQualityEvaluations.qualityEvaluationRules()
  Object.assign(ruleForm, result)
  issueTagsText.value = (result.issue_tags || []).join('，')
}

async function loadActive() {
  try {
    if (activeTab.value === 'tasks') await loadTasks()
    if (activeTab.value === 'records') await loadRecords()
    if (activeTab.value === 'review') await loadRecords('pending_verification')
    if (activeTab.value === 'stats') await loadStats()
    if (activeTab.value === 'rules') await loadRules()
    if (activeTab.value !== 'stats') await loadStats()
  } catch (error) {
    showToast(error.message || '评价数据加载失败', 'error')
  }
}

async function switchTab(key) {
  activeTab.value = key
  localStorage.setItem('processQualityEvaluationTab', key)
  await loadActive()
}

async function reviewRow(row, status) {
  const action = status === 'confirmed' ? '确认' : '驳回'
  if (!confirm(`确定${action}这条低分评价吗？`)) return
  await api.domains.processQualityEvaluations.reviewQualityEvaluation(row.id, { status, note: `主管${action}` })
  showToast(`评价已${action}`)
  await loadActive()
}

async function saveRules() {
  const issueTags = issueTagsText.value.split(/[，,]/).map(item => item.trim()).filter(Boolean)
  await api.domains.processQualityEvaluations.saveQualityEvaluationRules({
    enabled: ruleForm.enabled,
    required_previous_process: ruleForm.required_previous_process,
    low_score_threshold: ruleForm.low_score_threshold,
    issue_tags: issueTags,
  })
  showToast('评价规则已保存')
  await loadRules()
}

function issueText(row) {
  return [...(row.issue_tags || []), row.comment].filter(Boolean).join('；') || '-'
}

function statusText(status) {
  return { confirmed: '已确认', pending_verification: '待核验', rejected: '已驳回' }[status] || status
}

function statusClass(status) {
  return { confirmed: 'badge-success', pending_verification: 'badge-warning', rejected: 'badge-danger' }[status] || 'badge-info'
}

function scoreClass(score) {
  return score >= 80 ? 'text-success' : score >= 60 ? 'text-warning' : 'text-danger'
}

onMounted(async () => {
  if (!visibleTabs.value.some(tab => tab.key === activeTab.value)) activeTab.value = visibleTabs.value[0]?.key || 'tasks'
  await loadActive()
})
</script>

<style scoped>
.pqe-page{padding:var(--space-6)}
.pqe-toolbar{display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap}
.pqe-toolbar h3{margin:0}.pqe-subtitle{font-size:var(--text-xs-alt);color:var(--text-placeholder);margin-top:4px}
.pqe-tabs{display:flex;gap:var(--space-1);flex-wrap:wrap}.pqe-count{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;margin-left:4px;border-radius:10px;background:var(--danger);color:white;font-size:11px}
.pqe-filters{margin-left:auto;display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap}.pqe-search{width:260px}
.pqe-note{padding:10px 12px;margin-bottom:var(--space-3);border-left:3px solid var(--primary);background:var(--primary-light);color:var(--text-secondary);font-size:var(--text-sm)}
.pqe-table{min-width:1180px}.cell-muted{margin-top:3px;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.dimension-cell{white-space:nowrap;line-height:1.7}.action-cell{white-space:nowrap}.action-cell .btn+.btn{margin-left:6px}
.pqe-rules{max-width:760px}.pqe-rule-row{display:grid;grid-template-columns:150px 1fr;align-items:center;gap:var(--space-3);margin-bottom:var(--space-4)}.pqe-rule-row>label:first-child{font-weight:600;color:var(--text-secondary)}.switch-label{display:flex;align-items:center;gap:8px}.rule-input{display:flex;align-items:center;gap:10px}.rule-input .form-input{width:120px}.pqe-dimensions{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 var(--space-5) 150px}.pqe-dimensions span{padding:5px 8px;border:1px solid var(--border);background:var(--bg-hover);font-size:var(--text-xs-alt)}
@media(max-width:900px){.pqe-page{padding:var(--space-3)}.pqe-filters{margin-left:0;width:100%}.pqe-search{width:min(100%,260px)}.pqe-rule-row{grid-template-columns:1fr}.pqe-dimensions{margin-left:0}}
</style>
