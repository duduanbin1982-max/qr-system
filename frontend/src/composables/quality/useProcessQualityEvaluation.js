import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function useProcessQualityEvaluation() {
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

  const taskPage = ref(1), taskTotal = ref(0), recordPage = ref(1), recordTotal = ref(0), appealPage = ref(1), appealTotal = ref(0)

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

  const appealPages = computed(() => pageCount(appealTotal.value))

  function pageCount(total) { return Math.max(1, Math.ceil((Number(total) || 0) / PAGE_SIZE)) }

  function tabCount(key) { if (key === 'disposal') return disposalSummary.value.required_pending || 0; if (key === 'review') return statsSummary.value.pending_verification || 0; if (key === 'appeals') return appealSummary.value.pending || 0; return 0 }

  async function loadTasks() { const data = await api.domains.processQualityEvaluations.qualityEvaluationTasks({ scope: 'all', status: 'pending', keyword: keyword.value, page: taskPage.value, per_page: PAGE_SIZE }); const lastPage = pageCount(data.total); if (taskPage.value > lastPage) { taskPage.value = lastPage; return loadTasks() } tasks.value = data.items || []; taskTotal.value = data.total || 0 }

  async function loadRecords(status = '') { const data = await api.domains.processQualityEvaluations.qualityEvaluationRecords({ year_month: yearMonth.value, status, keyword: keyword.value, page: recordPage.value, per_page: PAGE_SIZE }); const lastPage = pageCount(data.total); if (recordPage.value > lastPage) { recordPage.value = lastPage; return loadRecords(status) } records.value = data.items || []; recordTotal.value = data.total || 0 }

  async function loadAppeals() { const data = await api.domains.processQualityEvaluations.qualityEvaluationAppeals({ status: '', year_month: yearMonth.value, page: appealPage.value, per_page: PAGE_SIZE }); const lastPage = pageCount(data.total); if (appealPage.value > lastPage) { appealPage.value = lastPage; return loadAppeals() } appeals.value = data.items || []; appealTotal.value = data.total || 0 }

  async function loadTemplates() { const [templateData, refData] = await Promise.all([api.domains.processQualityEvaluations.qualityEvaluationTemplates({}), api.domains.processQualityEvaluations.qualityEvaluationReferences()]); templates.value = templateData.items || []; Object.assign(refs, refData) }

  async function loadStats() { const data = await api.domains.processQualityEvaluations.qualityEvaluationStats({ year_month: yearMonth.value }); statsSummary.value = data.summary || {}; appealSummary.value = data.appeals || {}; processStats.value = data.processes || []; evaluatorStats.value = data.evaluators || [] }

  async function loadRules() { const data = await api.domains.processQualityEvaluations.qualityEvaluationRules(); Object.assign(ruleForm, data); issueTagsText.value = (data.issue_tags || []).join('，'); criticalTagsText.value = (data.critical_issue_tags || []).join('，') }

  async function loadActive({ resetDisposal = false } = {}) { try { if (activeTab.value === 'tasks') await loadTasks(); if (activeTab.value === 'disposal') { await nextTick(); await disposalView.value?.reload({ resetPage: resetDisposal }) } if (activeTab.value === 'records') await loadRecords(); if (activeTab.value === 'review') await loadRecords('pending_verification'); if (activeTab.value === 'appeals') await loadAppeals(); if (activeTab.value === 'templates') await loadTemplates(); if (activeTab.value === 'rules') await loadRules(); if (can('process_quality_evaluation:stats')) await loadStats() } catch (error) { showToast(error.message || '评价数据加载失败', 'error') } }

  function resetActivePage() { if (activeTab.value === 'tasks') taskPage.value = 1; if (['records', 'review'].includes(activeTab.value)) recordPage.value = 1; if (activeTab.value === 'appeals') appealPage.value = 1 }

  async function reloadActiveFromFirstPage() { resetActivePage(); await loadActive({ resetDisposal: true }) }

  async function switchTab(key) { activeTab.value = key; resetActivePage(); localStorage.setItem('processQualityEvaluationTab', key); await loadActive({ resetDisposal: true }) }

  function onDisposalSummary(value) { disposalSummary.value = value || {} }

  async function onTasksWaived() { taskPage.value = 1; await loadTasks() }

  async function changeTaskPage(delta) { taskPage.value += delta; await loadTasks() }

  async function changeRecordPage(delta) { recordPage.value += delta; await loadRecords(activeTab.value === 'review' ? 'pending_verification' : '') }

  async function changeAppealPage(delta) { appealPage.value += delta; await loadAppeals() }

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

  return {
    tabs,
    visibleTabs,
    canRules,
    activeTab,
    yearMonth,
    keyword,
    PAGE_SIZE,
    tasks,
    records,
    appeals,
    templates,
    taskPage,
    taskTotal,
    recordPage,
    recordTotal,
    appealPage,
    appealTotal,
    statsSummary,
    appealSummary,
    processStats,
    evaluatorStats,
    disposalSummary,
    disposalView,
    refs,
    ruleForm,
    issueTagsText,
    criticalTagsText,
    showTemplate,
    templateForm,
    templateTagsText,
    templateCriticalTagsText,
    showReview,
    reviewForm,
    reviewTitle,
    reviewTargetLabel,
    taskPages,
    recordPages,
    appealPages,
    pageCount,
    tabCount,
    loadTasks,
    loadRecords,
    loadAppeals,
    loadTemplates,
    loadStats,
    loadRules,
    loadActive,
    resetActivePage,
    reloadActiveFromFirstPage,
    switchTab,
    onDisposalSummary,
    onTasksWaived,
    changeTaskPage,
    changeRecordPage,
    changeAppealPage,
    splitTags,
    saveRules,
    openTemplate,
    addDimension,
    saveTemplate,
    openReview,
    saveReview,
    dimensionText,
    issueText,
    statusText,
    statusClass,
    severityText,
    severityClass,
    appealText,
    appealClass,
    scoreClass,
    scoreDeviation
  }
}
