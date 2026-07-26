<template>
  <div class="pqe-page">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">待</span><div><div class="s-val">{{ taskTotal }}</div><div class="s-label">待评价</div></div></div>
      <div class="summary-item"><span class="s-icon">必</span><div><div class="s-val text-danger">{{ disposalSummary.required_pending || 0 }}</div><div class="s-label">待处理必评</div></div></div>
      <div class="summary-item"><span class="s-icon">评</span><div><div class="s-val">{{ statsSummary.total || 0 }}</div><div class="s-label">评价总数</div></div></div>
      <div class="summary-item"><span class="s-icon">分</span><div><div class="s-val text-primary">{{ statsSummary.avg_score || 0 }}</div><div class="s-label">平均分</div></div></div>
      <div class="summary-item"><span class="s-icon">核</span><div><div class="s-val text-warning">{{ statsSummary.pending_verification || 0 }}</div><div class="s-label">待核验</div></div></div>
      <div class="summary-item"><span class="s-icon">诉</span><div><div class="s-val text-danger">{{ appealSummary.pending || 0 }}</div><div class="s-label">待处理申诉</div></div></div>
    </div>

    <div class="card pqe-shell">
      <div class="card-header pqe-toolbar">
        <div><h3>工序质量评价</h3><div class="pqe-subtitle">直接上道必评，历史工序选评，低分核验后再进入绩效</div></div>
        <div class="pqe-tabs">
          <button v-for="tab in visibleTabs" :key="tab.key" class="tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
            {{ tab.label }}
            <span v-if="tabCount(tab.key)" class="pqe-count">{{ tabCount(tab.key) }}</span>
          </button>
        </div>
        <div class="pqe-actions">
          <input v-if="!['stats','rules','templates'].includes(activeTab)" v-model="keyword" class="form-input pqe-search" placeholder="搜索订单、产品、序列号或工序" @keyup.enter="reloadActiveFromFirstPage">
          <input v-if="['records','review','appeals','stats'].includes(activeTab)" v-model="yearMonth" class="form-input pqe-month" type="month" @change="reloadActiveFromFirstPage">
          <button class="btn btn-default btn-sm" @click="loadActive()">刷新</button>
          <button v-if="activeTab === 'templates' && canRules" class="btn btn-primary btn-sm" @click="openTemplate()">新增模板</button>
        </div>
      </div>

      <div class="card-body pqe-body">
        <section v-if="activeTab === 'tasks'">
          <div class="pqe-note">任务在下道工序正常报工审批通过后生成。评价人提交前看不到被评价人员身份，主管在此处可查看完整归属。</div>
          <div class="table-wrap"><table v-if="tasks.length" class="data-table pqe-wide"><thead><tr><th>生成时间</th><th>订单/工件</th><th>产品</th><th>上游工序</th><th>被评价人</th><th>接手工序/评价人</th><th>模板</th><th>要求</th><th>归属</th></tr></thead>
            <tbody><tr v-for="task in tasks" :key="task.id"><td>{{ task.created_at }}</td><td><code>{{ task.order_no }}</code><div class="cell-muted">{{ task.serial_no || '订单模式' }}</div></td><td>{{ task.product_name }}<div class="cell-muted">{{ task.product_code || '-' }}</div></td><td>{{ task.target_process_name }}</td><td>{{ task.target_user_name || '工序整体' }}</td><td>{{ task.evaluator_process_name }}<div class="cell-muted">{{ task.evaluator_name }}</div></td><td>{{ task.template_snapshot?.name || '通用评价模板' }}</td><td><span class="badge" :class="task.is_required ? 'badge-warning' : 'badge-info'">{{ task.is_required ? '必评' : '选评' }}</span></td><td>{{ task.attribution_type === 'worker' ? '个人绩效' : '工序统计' }}</td></tr></tbody>
          </table><div v-else class="empty"><div class="empty-text">暂无待评价任务</div></div></div>
          <div v-if="taskTotal" class="pqe-pagination"><span>共 {{ taskTotal }} 条</span><button class="btn btn-default btn-sm" :disabled="taskPage <= 1" @click="changeTaskPage(-1)">上一页</button><span>第 {{ taskPage }} / {{ taskPages }} 页</span><button class="btn btn-default btn-sm" :disabled="taskPage >= taskPages" @click="changeTaskPage(1)">下一页</button></div>
        </section>

        <section v-else-if="activeTab === 'disposal'"><ProcessQualityTaskDisposal ref="disposalView" :keyword="keyword" @summary="onDisposalSummary" @waived="onTasksWaived" /></section>

        <section v-else-if="activeTab === 'records' || activeTab === 'review'">
          <div v-if="activeTab === 'review'" class="pqe-note">低分或严重问题先由质量人员核验。确认后才可进入绩效，驳回后评价不参与绩效计算。</div>
          <div class="table-wrap"><table v-if="records.length" class="data-table pqe-wide"><thead><tr><th>评价时间</th><th>订单/工件</th><th>上游工序/人员</th><th>接手工序/评价人</th><th>评分明细</th><th>总分</th><th>问题</th><th>严重度</th><th>申诉</th><th>状态</th><th v-if="activeTab === 'review'">操作</th></tr></thead>
            <tbody><tr v-for="row in records" :key="row.id"><td>{{ row.created_at }}</td><td><code>{{ row.order_no }}</code><div class="cell-muted">{{ row.serial_no || '订单模式' }}</div></td><td>{{ row.target_process_name }}<div class="cell-muted">{{ row.target_user_name || '工序整体' }}</div></td><td>{{ row.evaluator_process_name }}<div class="cell-muted">{{ row.evaluator_name }}</div></td><td class="dimension-cell">{{ dimensionText(row) }}</td><td><strong :class="scoreClass(row.total_score)">{{ row.total_score }}</strong><div class="cell-muted">{{ row.grade }}</div></td><td>{{ issueText(row) }}</td><td><span class="badge" :class="severityClass(row.severity)">{{ severityText(row.severity) }}</span></td><td>{{ appealText(row.appeal_status) }}</td><td><span class="badge" :class="statusClass(row.status)">{{ statusText(row.status) }}</span></td><td v-if="activeTab === 'review'" class="action-cell"><button class="btn btn-success btn-sm" @click="openReview('evaluation', row, 'confirmed')">确认</button><button class="btn btn-default btn-sm" @click="openReview('evaluation', row, 'rejected')">驳回</button></td></tr></tbody>
          </table><div v-else class="empty"><div class="empty-text">暂无评价记录</div></div></div>
          <div v-if="recordTotal" class="pqe-pagination"><span>共 {{ recordTotal }} 条</span><button class="btn btn-default btn-sm" :disabled="recordPage <= 1" @click="changeRecordPage(-1)">上一页</button><span>第 {{ recordPage }} / {{ recordPages }} 页</span><button class="btn btn-default btn-sm" :disabled="recordPage >= recordPages" @click="changeRecordPage(1)">下一页</button></div>
        </section>

        <section v-else-if="activeTab === 'appeals'">
          <div class="pqe-note">待处理申诉在复核完成前自动排除出绩效计算。申诉成立后原评价转为驳回，所有处理说明永久留痕。</div>
          <div class="table-wrap"><table v-if="appeals.length" class="data-table pqe-wide"><thead><tr><th>申诉时间</th><th>订单/工件</th><th>工序/申诉人</th><th>原评分</th><th>申诉原因</th><th>状态</th><th>复核人/说明</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in appeals" :key="row.id"><td>{{ row.created_at }}</td><td><code>{{ row.order_no }}</code><div class="cell-muted">{{ row.serial_no || '订单模式' }}</div></td><td>{{ row.target_process_name }}<div class="cell-muted">{{ row.requester_name }}</div></td><td><strong :class="scoreClass(row.total_score)">{{ row.total_score }}</strong><div class="cell-muted">{{ row.grade }}</div></td><td>{{ row.reason }}</td><td><span class="badge" :class="appealClass(row.status)">{{ appealText(row.status) }}</span></td><td>{{ row.reviewer_name || '-' }}<div class="cell-muted">{{ row.review_note || '-' }}</div></td><td class="action-cell"><template v-if="row.status === 'pending'"><button class="btn btn-success btn-sm" @click="openReview('appeal', row, 'accepted')">成立</button><button class="btn btn-default btn-sm" @click="openReview('appeal', row, 'rejected')">不成立</button></template></td></tr></tbody>
          </table><div v-else class="empty"><div class="empty-text">暂无申诉记录</div></div></div>
        </section>

        <section v-else-if="activeTab === 'templates'">
          <div class="pqe-note">优先匹配“工序路线 + 工序”模板，没有路线专属模板时使用该工序的通用模板，再没有时使用系统通用维度。</div>
          <div class="table-wrap"><table v-if="templates.length" class="data-table pqe-wide"><thead><tr><th>模板名称</th><th>工序路线</th><th>工序</th><th>评分维度</th><th>低分阈值</th><th>严重阈值</th><th>问题标签</th><th>状态</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in templates" :key="row.id"><td>{{ row.name }}</td><td>{{ row.route_name || '全部路线' }}</td><td>{{ row.process_name }}</td><td>{{ row.dimensions.map(item => `${item.label}×${item.weight}`).join('、') }}</td><td>{{ row.low_score_threshold }}</td><td>{{ row.critical_score_threshold }}</td><td>{{ row.issue_tags.join('、') || '-' }}</td><td><span class="badge" :class="row.status === 'active' ? 'badge-success' : 'badge-info'">{{ row.status === 'active' ? '启用' : '停用' }}</span></td><td><button class="btn btn-default btn-sm" @click="openTemplate(row)">编辑</button></td></tr></tbody>
          </table><div v-else class="empty"><div class="empty-text">暂无工序专属评价模板，当前使用系统通用维度</div></div></div>
        </section>

        <section v-else-if="activeTab === 'stats'">
          <div class="pqe-note">达到最小样本数、已确认、明确归属个人且没有待处理申诉的评价才进入绩效。评价人均分明显偏离整体均分时应进行校准复核。</div>
          <div class="pqe-stats-grid">
            <div><div class="pqe-section-head"><h4>工序质量趋势</h4></div><div class="table-wrap"><table v-if="processStats.length" class="data-table"><thead><tr><th>工序</th><th>评价次数</th><th>平均分</th><th>低分</th><th>状态</th></tr></thead><tbody><tr v-for="row in processStats" :key="row.process_id"><td>{{ row.process_name }}</td><td>{{ row.evaluation_count }}</td><td><strong :class="scoreClass(row.avg_score)">{{ row.avg_score }}</strong></td><td>{{ row.low_score_count }}</td><td>{{ row.avg_score >= 80 ? '稳定' : row.avg_score >= 60 ? '关注' : '需改进' }}</td></tr></tbody></table></div></div>
            <div><div class="pqe-section-head"><h4>评价人偏差</h4></div><div class="table-wrap"><table v-if="evaluatorStats.length" class="data-table"><thead><tr><th>评价人</th><th>次数</th><th>平均分</th><th>低分</th><th>偏差</th></tr></thead><tbody><tr v-for="row in evaluatorStats" :key="row.evaluator_user_id"><td>{{ row.evaluator_name }}</td><td>{{ row.evaluation_count }}</td><td>{{ row.avg_score }}</td><td>{{ row.low_score_count }}</td><td :class="Math.abs(scoreDeviation(row)) >= 15 ? 'text-danger' : ''">{{ scoreDeviation(row) > 0 ? '+' : '' }}{{ scoreDeviation(row) }}</td></tr></tbody></table></div></div>
          </div>
        </section>

        <section v-else class="pqe-rules">
          <div class="pqe-rule-grid">
            <label><span>启用工序质量评价</span><input v-model="ruleForm.enabled" type="checkbox"></label>
            <label><span>直接上一道工序必评</span><input v-model="ruleForm.required_previous_process" type="checkbox"></label>
            <label><span>移动端报工后自动打开</span><input v-model="ruleForm.auto_open_mobile" type="checkbox"></label>
            <label><span>提交前隐藏被评价人</span><input v-model="ruleForm.hide_target_identity" type="checkbox"></label>
            <label><span>低分核验阈值</span><input v-model.number="ruleForm.low_score_threshold" class="form-input" type="number" min="0" max="100"></label>
            <label><span>严重缺陷阈值</span><input v-model.number="ruleForm.critical_score_threshold" class="form-input" type="number" min="0" max="100"></label>
            <label><span>进入绩效最小样本数</span><input v-model.number="ruleForm.minimum_samples_for_performance" class="form-input" type="number" min="1"></label>
          </div>
          <label class="pqe-full-label">通用问题标签<textarea v-model="issueTagsText" class="form-input" rows="3" placeholder="用逗号分隔"></textarea></label>
          <label class="pqe-full-label">严重问题标签<textarea v-model="criticalTagsText" class="form-input" rows="2" placeholder="用逗号分隔"></textarea></label>
          <button class="btn btn-primary" @click="saveRules">保存评价规则</button>
        </section>
      </div>
    </div>

    <div v-if="showTemplate" class="modal-overlay"><div class="modal pqe-modal pqe-modal-wide"><div class="modal-header"><span>{{ templateForm.id ? '编辑评价模板' : '新增评价模板' }}</span><span class="modal-close" @click="showTemplate=false">&times;</span></div><div class="modal-body">
      <div class="pqe-form-grid"><label>模板名称<input v-model="templateForm.name" class="form-input"></label><label>工序路线<select v-model="templateForm.route_id" class="form-input"><option :value="null">全部路线</option><option v-for="row in refs.routes" :key="row.id" :value="row.id">{{ row.name }}</option></select></label><label>目标工序<select v-model="templateForm.process_id" class="form-input"><option :value="null">请选择</option><option v-for="row in refs.processes" :key="row.id" :value="row.id">{{ row.name }}</option></select></label><label>状态<select v-model="templateForm.status" class="form-input"><option value="active">启用</option><option value="inactive">停用</option></select></label><label>低分阈值<input v-model.number="templateForm.low_score_threshold" type="number" min="0" max="100" class="form-input"></label><label>严重阈值<input v-model.number="templateForm.critical_score_threshold" type="number" min="0" max="100" class="form-input"></label></div>
      <div class="pqe-section-head"><h4>评分维度</h4><button class="btn btn-default btn-sm" @click="addDimension">新增维度</button></div>
      <div class="table-wrap"><table class="data-table pqe-dimension-table"><thead><tr><th>编码</th><th>名称</th><th>权重</th><th>必评</th><th></th></tr></thead><tbody><tr v-for="(row,index) in templateForm.dimensions" :key="index"><td><input v-model="row.key" class="form-input"></td><td><input v-model="row.label" class="form-input"></td><td><input v-model.number="row.weight" type="number" min="1" class="form-input"></td><td><input v-model="row.required" type="checkbox"></td><td><button class="btn btn-danger btn-sm" @click="templateForm.dimensions.splice(index,1)">删除</button></td></tr></tbody></table></div>
      <label class="pqe-full-label">问题标签<textarea v-model="templateTagsText" class="form-input" rows="2" placeholder="用逗号分隔"></textarea></label><label class="pqe-full-label">严重问题标签<textarea v-model="templateCriticalTagsText" class="form-input" rows="2" placeholder="用逗号分隔"></textarea></label>
    </div><div class="modal-footer"><button class="btn btn-default" @click="showTemplate=false">取消</button><button class="btn btn-primary" @click="saveTemplate">保存</button></div></div></div>

    <div v-if="showReview" class="modal-overlay"><div class="modal pqe-modal"><div class="modal-header"><span>{{ reviewTitle }}</span><span class="modal-close" @click="showReview=false">&times;</span></div><div class="modal-body"><div class="pqe-review-meta">{{ reviewTargetLabel }}</div><label class="pqe-full-label">处理说明<textarea v-model="reviewForm.note" rows="4" class="form-input" placeholder="填写现场核验依据和处理结论"></textarea></label></div><div class="modal-footer"><button class="btn btn-default" @click="showReview=false">取消</button><button class="btn btn-primary" @click="saveReview">确认提交</button></div></div></div>

  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import ProcessQualityTaskDisposal from '@/components/ProcessQualityTaskDisposal.vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const tabs = [
  { key: 'tasks', label: '待评价' }, { key: 'records', label: '评价记录' },
  { key: 'disposal', label: '任务处置', permission: 'process_quality_evaluation:waive' },
  { key: 'review', label: '异常核验', permission: 'process_quality_evaluation:review' },
  { key: 'appeals', label: '申诉复核', permission: 'process_quality_evaluation:review' },
  { key: 'templates', label: '评价模板', permission: 'process_quality_evaluation:rules' },
  { key: 'stats', label: '统计分析', permission: 'process_quality_evaluation:stats' },
  { key: 'rules', label: '评价规则', permission: 'process_quality_evaluation:rules' },
]
const visibleTabs = computed(() => tabs.filter(tab => !tab.permission || can(tab.permission)))
const canRules = computed(() => can('process_quality_evaluation:rules'))
const activeTab = ref(localStorage.getItem('processQualityEvaluationTab') || 'tasks')
const yearMonth = ref(new Date().toISOString().slice(0, 7))
const keyword = ref('')
const PAGE_SIZE = 50
const tasks = ref([]), records = ref([]), appeals = ref([]), templates = ref([])
const taskPage = ref(1), taskTotal = ref(0), recordPage = ref(1), recordTotal = ref(0)
const statsSummary = ref({}), appealSummary = ref({}), processStats = ref([]), evaluatorStats = ref([])
const disposalSummary = ref({}), disposalView = ref(null)
const refs = reactive({ routes: [], processes: [] })
const ruleForm = reactive({ enabled: true, required_previous_process: true, auto_open_mobile: true, hide_target_identity: true, low_score_threshold: 60, critical_score_threshold: 40, minimum_samples_for_performance: 3 })
const issueTagsText = ref(''), criticalTagsText = ref('')
const showTemplate = ref(false), templateForm = reactive({}), templateTagsText = ref(''), templateCriticalTagsText = ref('')
const showReview = ref(false), reviewForm = reactive({ type: '', target: null, status: '', note: '' })
const reviewTitle = computed(() => reviewForm.type === 'appeal' ? (reviewForm.status === 'accepted' ? '确认申诉成立' : '确认申诉不成立') : (reviewForm.status === 'confirmed' ? '确认低分评价' : '驳回低分评价'))
const reviewTargetLabel = computed(() => reviewForm.target ? `${reviewForm.target.order_no || ''} · ${reviewForm.target.target_process_name || ''} · ${reviewForm.target.total_score || 0}分` : '')

const taskPages = computed(() => pageCount(taskTotal.value))
const recordPages = computed(() => pageCount(recordTotal.value))

function pageCount(total) { return Math.max(1, Math.ceil((Number(total) || 0) / PAGE_SIZE)) }
function tabCount(key) { if (key === 'disposal') return disposalSummary.value.required_pending || 0; if (key === 'review') return statsSummary.value.pending_verification || 0; if (key === 'appeals') return appealSummary.value.pending || 0; return 0 }
async function loadTasks() { const data = await api.domains.processQualityEvaluations.qualityEvaluationTasks({ scope: 'all', status: 'pending', keyword: keyword.value, page: taskPage.value, per_page: PAGE_SIZE }); const lastPage = pageCount(data.total); if (taskPage.value > lastPage) { taskPage.value = lastPage; return loadTasks() } tasks.value = data.items || []; taskTotal.value = data.total || 0 }
async function loadRecords(status = '') { const data = await api.domains.processQualityEvaluations.qualityEvaluationRecords({ year_month: yearMonth.value, status, keyword: keyword.value, page: recordPage.value, per_page: PAGE_SIZE }); const lastPage = pageCount(data.total); if (recordPage.value > lastPage) { recordPage.value = lastPage; return loadRecords(status) } records.value = data.items || []; recordTotal.value = data.total || 0 }
async function loadAppeals() { const data = await api.domains.processQualityEvaluations.qualityEvaluationAppeals({ status: '', year_month: yearMonth.value }); appeals.value = data.items || [] }
async function loadTemplates() { const [templateData, refData] = await Promise.all([api.domains.processQualityEvaluations.qualityEvaluationTemplates({}), api.domains.processQualityEvaluations.qualityEvaluationReferences()]); templates.value = templateData.items || []; Object.assign(refs, refData) }
async function loadStats() { const data = await api.domains.processQualityEvaluations.qualityEvaluationStats({ year_month: yearMonth.value }); statsSummary.value = data.summary || {}; appealSummary.value = data.appeals || {}; processStats.value = data.processes || []; evaluatorStats.value = data.evaluators || [] }
async function loadRules() { const data = await api.domains.processQualityEvaluations.qualityEvaluationRules(); Object.assign(ruleForm, data); issueTagsText.value = (data.issue_tags || []).join('，'); criticalTagsText.value = (data.critical_issue_tags || []).join('，') }
async function loadActive({ resetDisposal = false } = {}) { try { if (activeTab.value === 'tasks') await loadTasks(); if (activeTab.value === 'disposal') { await nextTick(); await disposalView.value?.reload({ resetPage: resetDisposal }) } if (activeTab.value === 'records') await loadRecords(); if (activeTab.value === 'review') await loadRecords('pending_verification'); if (activeTab.value === 'appeals') await loadAppeals(); if (activeTab.value === 'templates') await loadTemplates(); if (activeTab.value === 'rules') await loadRules(); if (can('process_quality_evaluation:stats')) await loadStats() } catch (error) { showToast(error.message || '评价数据加载失败', 'error') } }
function resetActivePage() { if (activeTab.value === 'tasks') taskPage.value = 1; if (['records', 'review'].includes(activeTab.value)) recordPage.value = 1 }
async function reloadActiveFromFirstPage() { resetActivePage(); await loadActive({ resetDisposal: true }) }
async function switchTab(key) { activeTab.value = key; resetActivePage(); localStorage.setItem('processQualityEvaluationTab', key); await loadActive({ resetDisposal: true }) }
function onDisposalSummary(value) { disposalSummary.value = value || {} }
async function onTasksWaived() { taskPage.value = 1; await loadTasks() }
async function changeTaskPage(delta) { taskPage.value += delta; await loadTasks() }
async function changeRecordPage(delta) { recordPage.value += delta; await loadRecords(activeTab.value === 'review' ? 'pending_verification' : '') }

function splitTags(value) { return value.split(/[，,]/).map(item => item.trim()).filter(Boolean) }
async function saveRules() { try { await api.domains.processQualityEvaluations.saveQualityEvaluationRules({ ...ruleForm, issue_tags: splitTags(issueTagsText.value), critical_issue_tags: splitTags(criticalTagsText.value) }); showToast('评价规则已保存'); await loadRules() } catch (error) { showToast(error.message || '保存失败', 'error') } }
function openTemplate(row = null) { Object.assign(templateForm, row ? JSON.parse(JSON.stringify(row)) : { id: null, name: '', route_id: null, process_id: null, low_score_threshold: ruleForm.low_score_threshold || 60, critical_score_threshold: ruleForm.critical_score_threshold || 40, status: 'active', dimensions: [{ key: 'processing_quality', label: '加工质量', weight: 1, required: true }] }); templateTagsText.value = (row?.issue_tags || []).join('，'); templateCriticalTagsText.value = (row?.critical_issue_tags || []).join('，'); showTemplate.value = true }
function addDimension() { templateForm.dimensions.push({ key: '', label: '', weight: 1, required: true }) }
async function saveTemplate() { try { const payload = { ...templateForm, issue_tags: splitTags(templateTagsText.value), critical_issue_tags: splitTags(templateCriticalTagsText.value) }; if (templateForm.id) await api.domains.processQualityEvaluations.updateQualityEvaluationTemplate(templateForm.id, payload); else await api.domains.processQualityEvaluations.createQualityEvaluationTemplate(payload); showTemplate.value = false; showToast('评价模板已保存'); await loadTemplates() } catch (error) { showToast(error.message || '模板保存失败', 'error') } }
function openReview(type, target, status) { Object.assign(reviewForm, { type, target, status, note: '' }); showReview.value = true }
async function saveReview() { if (!reviewForm.note.trim()) { showToast('请填写处理说明', 'error'); return } try { if (reviewForm.type === 'appeal') await api.domains.processQualityEvaluations.reviewQualityEvaluationAppeal(reviewForm.target.id, { status: reviewForm.status, note: reviewForm.note }); else await api.domains.processQualityEvaluations.reviewQualityEvaluation(reviewForm.target.id, { status: reviewForm.status, note: reviewForm.note }); showReview.value = false; showToast('复核结果已保存'); await loadActive() } catch (error) { showToast(error.message || '复核失败', 'error') } }

function dimensionText(row) { const labels = Object.fromEntries((row.template_snapshot?.dimensions || []).map(item => [item.key, item.label])); const values = row.dimension_scores || {}; const entries = Object.entries(values); if (entries.length) return entries.map(([key, value]) => `${labels[key] || key} ${value}分`).join(' / '); return `加工 ${row.processing_quality} / 精度 ${row.dimensional_accuracy} / 外观 ${row.appearance_quality} / 接续 ${row.process_continuity} / 防护 ${row.cleanliness_protection}` }
function issueText(row) { return [...(row.issue_tags || []), row.comment].filter(Boolean).join('；') || '-' }
function statusText(value) { return { confirmed: '已确认', pending_verification: '待核验', rejected: '已驳回' }[value] || value }
function statusClass(value) { return { confirmed: 'badge-success', pending_verification: 'badge-warning', rejected: 'badge-danger' }[value] || 'badge-info' }
function severityText(value) { return { normal: '正常', warning: '预警', critical: '严重' }[value] || '正常' }
function severityClass(value) { return value === 'critical' ? 'badge-danger' : value === 'warning' ? 'badge-warning' : 'badge-success' }
function appealText(value) { return { pending: '待复核', accepted: '申诉成立', rejected: '申诉不成立' }[value] || '-' }
function appealClass(value) { return value === 'accepted' ? 'badge-success' : value === 'rejected' ? 'badge-info' : 'badge-warning' }
function scoreClass(score) { return score >= 80 ? 'text-success' : score >= 60 ? 'text-warning' : 'text-danger' }
function scoreDeviation(row) { return Math.round(((row.avg_score || 0) - (statsSummary.value.avg_score || 0)) * 10) / 10 }
onMounted(async () => { if (!visibleTabs.value.some(tab => tab.key === activeTab.value)) activeTab.value = visibleTabs.value[0]?.key || 'tasks'; await loadActive() })
</script>

<style scoped>
.pqe-page{padding:var(--space-6)}.pqe-shell{min-height:620px}.pqe-toolbar{display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap}.pqe-toolbar h3{margin:0}.pqe-subtitle{font-size:var(--text-xs-alt);color:var(--text-placeholder);margin-top:4px}.pqe-tabs{display:flex;gap:var(--space-1);flex-wrap:wrap}.pqe-count{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;margin-left:4px;border-radius:10px;background:var(--danger);color:#fff;font-size:11px}.pqe-actions{margin-left:auto;display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap}.pqe-search{width:240px}.pqe-month{width:150px}.pqe-body{padding-top:var(--space-3)}.pqe-wide{min-width:1320px}.cell-muted{margin-top:3px;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.dimension-cell{max-width:320px;white-space:normal;line-height:1.6}.action-cell{white-space:nowrap}.action-cell .btn+.btn{margin-left:6px}.pqe-note{padding:10px 12px;margin-bottom:var(--space-3);border-left:3px solid var(--primary);background:var(--primary-light);color:var(--text-secondary);font-size:var(--text-sm)}.pqe-stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-6)}.pqe-section-head{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);margin:var(--space-4) 0 var(--space-3)}.pqe-section-head h4{margin:0}.pqe-rules{max-width:900px}.pqe-rule-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-3) var(--space-6)}.pqe-rule-grid label{display:grid;grid-template-columns:1fr 150px;align-items:center;gap:var(--space-3);padding:9px 0;border-bottom:1px solid var(--border)}.pqe-rule-grid input[type=checkbox]{justify-self:end;width:18px;height:18px}.pqe-full-label{display:flex;flex-direction:column;gap:6px;margin:var(--space-3) 0;color:var(--text-secondary);font-size:var(--text-sm)}.pqe-modal{width:min(720px,94vw);max-height:88vh;display:flex;flex-direction:column}.pqe-modal-wide{width:min(1040px,96vw)}.pqe-modal .modal-body{overflow:auto}.pqe-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-3)}.pqe-form-grid label{display:flex;flex-direction:column;gap:6px;color:var(--text-secondary);font-size:var(--text-sm)}.pqe-dimension-table{min-width:760px}.pqe-dimension-table .form-input{min-width:100px}.pqe-review-meta{padding:10px 12px;background:var(--bg-hover);font-weight:600}.pqe-pagination{display:flex;align-items:center;justify-content:flex-end;gap:var(--space-3);padding-top:var(--space-3);color:var(--text-secondary);font-size:var(--text-sm)}
@media(max-width:900px){.pqe-page{padding:var(--space-3)}.pqe-actions{margin-left:0;width:100%}.pqe-search{width:min(100%,240px)}.pqe-stats-grid,.pqe-rule-grid,.pqe-form-grid{grid-template-columns:1fr}.pqe-rule-grid label{grid-template-columns:1fr 130px}.pqe-pagination{justify-content:flex-start;flex-wrap:wrap}}
</style>
