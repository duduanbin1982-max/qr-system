import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


function commandKey(action, target = 'month') {
  const nonce = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}:${Math.random().toString(36).slice(2)}`
  return `performance-ui:${action}:${target}:${nonce}`
}

function conflictMessage(error) {
  if (error?.status === 409 || error?.code === 409) {
    return `数据冲突：${error.message || '记录已更新，请核对最新状态'}`
  }
  return error?.message || '绩效操作失败'
}

function normalizeBatchScore(row) {
  let details = row?.score_details
  if (!details && row?.score_details_json) {
    try { details = JSON.parse(row.score_details_json) } catch (_) { details = {} }
  }
  return {
    ...row,
    user_name: row.user_name || row.employee_name_snapshot || '',
    employee_no: row.employee_no || row.employee_no_snapshot || '',
    department_name: row.department_name || row.department_name_snapshot || '',
    position_name: row.position_name || row.position_name_snapshot || '',
    eligible: row.eligible === true || row.eligibility_status === 'eligible',
    score_details: details && typeof details === 'object' ? details : {},
  }
}

export function usePerformancePageData() {
  const yearMonth = ref(new Date().toISOString().slice(0, 7))
  const warningLevel = ref('')
  const positionId = ref('')
  const search = ref('')
  const scores = ref([])
  const scoreResult = ref({})
  const overview = ref({})
  const plans = ref([])
  const planDetail = ref(null)
  const summary = ref({})
  const positionOptions = ref([])
  const rules = ref({})
  const loading = ref(false)
  const working = ref(false)

  const batches = ref([])
  const selectedBatchId = ref(null)
  const batchDetail = ref(null)
  const comparison = ref(null)
  const exceptions = ref([])
  const exceptionTotal = ref(0)
  const ruleVersions = ref([])
  const targets = ref([])
  const positions = ref([])
  const scopeUsers = ref([])
  const scopeDepartments = ref([])
  const selectedScopeUserId = ref(null)
  const selectedDepartmentIds = ref([])

  async function loadRules() {
    rules.value = await api.domains.performance.performanceRules()
  }

  async function loadOverview() {
    const data = await api.domains.performance.performanceOverview({ year_month: yearMonth.value })
    overview.value = data || {}
    if (data?.display_month && data.display_month !== yearMonth.value) {
      yearMonth.value = data.display_month
    }
  }

  async function loadScoreRows() {
    const data = await api.domains.performance.performanceScores({
      year_month: yearMonth.value,
      warning_level: warningLevel.value,
      position_id: positionId.value,
      search: search.value.trim(),
      per_page: 200,
    })
    scoreResult.value = data || {}
    scores.value = data.items || []
    summary.value = data.summary || {}
    positionOptions.value = data.position_options || []
  }

  async function loadScores() {
    loading.value = true
    try {
      await loadScoreRows()
    } catch (error) {
      showToast(error.message || '正式绩效结果加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  async function loadPlans() {
    try {
      const data = await api.domains.performance.performancePlans({
        production_month: yearMonth.value,
      })
      plans.value = data.plans || []
    } catch (error) {
      showToast(error.message || '改进计划加载失败', 'error')
    }
  }

  async function loadPlanDetail(planId) {
    try {
      planDetail.value = await api.domains.performance.getPerformancePlan(planId)
      return planDetail.value
    } catch (error) {
      showToast(error.message || '改进计划详情加载失败', 'error')
      return null
    }
  }

  async function refreshFormalResults() {
    await Promise.all([loadScoreRows(), loadPlans()])
  }

  async function loadBatchDetail(id = selectedBatchId.value) {
    if (!id) {
      batchDetail.value = null
      return
    }
    selectedBatchId.value = Number(id)
    const detail = await api.domains.performance.performanceBatchDetail(id, { per_page: 200 })
    batchDetail.value = {
      ...detail,
      scores: (detail.scores || []).map(normalizeBatchScore),
    }
  }

  async function loadBatches() {
    try {
      const data = await api.domains.performance.listPerformanceBatches({
        production_month: yearMonth.value,
        per_page: 100,
      })
      batches.value = data.items || []
      const selected = batches.value.find(item => Number(item.id) === Number(selectedBatchId.value))
      selectedBatchId.value = selected?.id || batches.value[0]?.id || null
      await loadBatchDetail()
    } catch (error) {
      showToast(error.message || '绩效批次加载失败', 'error')
    }
  }

  async function refreshBatchAfterConflict(error) {
    await loadBatches()
    showToast(conflictMessage(error), 'error')
  }

  async function executeBatchCommand(call, successMessage) {
    if (working.value) return
    working.value = true
    try {
      await call()
      showToast(successMessage)
      await loadBatches()
    } catch (error) {
      if (error?.status === 409 || error?.code === 409) {
        await refreshBatchAfterConflict(error)
      } else {
        showToast(error.message || '绩效批次操作失败', 'error')
      }
    } finally {
      working.value = false
    }
  }

  function batchCommand(batch, action, extra = {}) {
    return {
      row_version: batch.row_version,
      idempotency_key: commandKey(action, batch.id),
      ...extra,
    }
  }

  function createBatch() {
    return executeBatchCommand(
      () => api.domains.performance.createPerformanceBatch({
        production_month: yearMonth.value,
        idempotency_key: commandKey('create-batch', yearMonth.value),
        revision_reason: '月度绩效制单',
      }),
      '绩效批次草稿已生成',
    )
  }

  function submitSupervisorReview(batch) {
    return executeBatchCommand(
      () => api.domains.performance.submitPerformanceSupervisorReview(
        batch.id,
        batchCommand(batch, 'submit-supervisor-review'),
      ),
      '批次已提交主管复核',
    )
  }

  function submitApproval(batch) {
    return executeBatchCommand(
      () => api.domains.performance.submitPerformanceApproval(
        batch.id,
        batchCommand(batch, 'submit-approval'),
      ),
      '批次已提交批准',
    )
  }

  function approveBatch(batch) {
    return executeBatchCommand(
      () => api.domains.performance.approvePerformanceBatch(
        batch.id,
        batchCommand(batch, 'approve'),
      ),
      '批次已批准并切换为正式版本',
    )
  }

  function returnBatch(batch, reason) {
    return executeBatchCommand(
      () => api.domains.performance.returnPerformanceBatch(
        batch.id,
        batchCommand(batch, 'return', { reason }),
      ),
      '批次已退回',
    )
  }

  function cancelBatch(batch, reason) {
    return executeBatchCommand(
      () => api.domains.performance.cancelPerformanceBatch(
        batch.id,
        batchCommand(batch, 'cancel', { reason }),
      ),
      '批次已取消',
    )
  }

  function createRevision(batch, reason) {
    return executeBatchCommand(
      () => api.domains.performance.createPerformanceRevision(
        batch.id,
        batchCommand(batch, 'revision', { reason }),
      ),
      '绩效修订版草稿已生成',
    )
  }

  function saveReview(score, reviewForm) {
    const batch = batchDetail.value?.batch || batchDetail.value
    return executeBatchCommand(
      () => api.domains.performance.savePerformanceSupervisorReview(
        batch.id,
        score.user_id,
        batchCommand(batch, 'member-review', { review: { ...reviewForm } }),
      ),
      '主管复核已保存，岗位排名已重算',
    )
  }

  async function loadComparison(baseBatchId, compareBatchId) {
    if (!baseBatchId || !compareBatchId || Number(baseBatchId) === Number(compareBatchId)) {
      comparison.value = null
      return
    }
    try {
      comparison.value = await api.domains.performance.performanceBatchComparison(
        baseBatchId,
        compareBatchId,
      )
    } catch (error) {
      showToast(error.message || '绩效版本对比加载失败', 'error')
    }
  }

  async function loadExceptions(batchId = selectedBatchId.value || scoreResult.value.batch_id) {
    if (!batchId) {
      exceptions.value = []
      exceptionTotal.value = 0
      return
    }
    try {
      const data = await api.domains.performance.performanceBatchExceptions(batchId, { per_page: 200 })
      exceptions.value = data.items || []
      exceptionTotal.value = data.total || 0
    } catch (error) {
      showToast(error.message || '绩效数据异常加载失败', 'error')
    }
  }

  async function loadConfiguration() {
    try {
      const [ruleData, targetData, positionData] = await Promise.all([
        api.domains.performance.listPerformanceRuleVersions(),
        api.domains.performance.listPerformanceTargets(),
        api.domains.positions.listPositions(),
      ])
      ruleVersions.value = Array.isArray(ruleData) ? ruleData : ruleData.items || []
      targets.value = Array.isArray(targetData) ? targetData : targetData.items || []
      positions.value = Array.isArray(positionData) ? positionData : positionData.positions || []
    } catch (error) {
      showToast(error.message || '岗位目标加载失败', 'error')
    }
  }

  async function createTarget(form) {
    if (working.value) return
    working.value = true
    try {
      await api.domains.performance.createPerformanceTarget({ ...form })
      showToast('岗位目标草稿已创建')
      await loadConfiguration()
    } catch (error) {
      showToast(error.message || '岗位目标保存失败', 'error')
    } finally {
      working.value = false
    }
  }

  async function approveTarget(target) {
    if (working.value) return
    working.value = true
    try {
      await api.domains.performance.approvePerformanceTarget(target.id, { row_version: target.row_version })
      showToast('岗位目标已批准')
      await loadConfiguration()
    } catch (error) {
      if (error?.status === 409 || error?.code === 409) await loadConfiguration()
      showToast(conflictMessage(error), 'error')
    } finally {
      working.value = false
    }
  }

  async function createPlan(selectedScore, planForm) {
    try {
      await api.domains.performance.createPerformancePlan({
        score_revision_id: selectedScore.id,
        user_id: selectedScore.user_id,
        production_month: yearMonth.value,
        warning_level: selectedScore.warning_level,
        idempotency_key: commandKey('create-plan', selectedScore.user_id),
        ...planForm,
      })
      showToast('改进计划草稿已创建')
      await loadPlans()
    } catch (error) {
      showToast(error.message || '改进计划创建失败', 'error')
      throw error
    }
  }

  async function executePlanCommand(call, successMessage) {
    if (working.value) return
    working.value = true
    try {
      await call()
      showToast(successMessage)
      await loadPlans()
    } catch (error) {
      if (error?.status === 409 || error?.code === 409) await loadPlans()
      showToast(conflictMessage(error), 'error')
    } finally {
      working.value = false
    }
  }

  function activatePlan(plan) {
    return executePlanCommand(
      () => api.domains.performance.transitionPerformancePlan(plan.id, {
        target_status: 'active',
        row_version: plan.row_version,
        idempotency_key: commandKey('activate-plan', plan.id),
      }),
      '改进计划已激活',
    )
  }

  function addPlanEvidence(plan, evidence) {
    return executePlanCommand(
      () => api.domains.performance.addPerformancePlanEvidence(plan.id, {
        ...evidence,
        row_version: plan.row_version,
        idempotency_key: commandKey('plan-evidence', plan.id),
      }),
      '改进证据已追加',
    )
  }

  function requestPlanReassessment(plan) {
    return executePlanCommand(
      () => api.domains.performance.transitionPerformancePlan(plan.id, {
        target_status: 'reassessment_pending',
        row_version: plan.row_version,
        idempotency_key: commandKey('request-reassessment', plan.id),
      }),
      '改进计划已提交复评',
    )
  }

  function reassessPlan(plan, reassessment) {
    return executePlanCommand(
      () => api.domains.performance.reassessPerformancePlan(plan.id, {
        ...reassessment,
        row_version: plan.row_version,
        idempotency_key: commandKey('reassess-plan', plan.id),
      }),
      reassessment.result === 'passed' ? '复评通过，计划已关闭' : '复评未通过，计划已回到执行中',
    )
  }

  async function loadScopeSupport() {
    try {
      const [userData, departmentData] = await Promise.all([
        api.domains.users.listUsers({ page: 1, limit: 500 }),
        api.domains.performance.listPerformanceDepartments(),
      ])
      scopeUsers.value = userData.users || userData.items || []
      scopeDepartments.value = departmentData.flat || departmentData.departments || departmentData.items || departmentData || []
      if (!selectedScopeUserId.value && scopeUsers.value.length) {
        selectedScopeUserId.value = scopeUsers.value[0].id
      }
      await loadDepartmentScope(selectedScopeUserId.value)
    } catch (error) {
      showToast(error.message || '部门授权数据加载失败', 'error')
    }
  }

  async function loadDepartmentScope(userId) {
    selectedScopeUserId.value = Number(userId) || null
    if (!selectedScopeUserId.value) {
      selectedDepartmentIds.value = []
      return
    }
    try {
      const data = await api.domains.performance.getPerformanceDepartmentScopes(selectedScopeUserId.value)
      selectedDepartmentIds.value = (data.department_ids || []).map(Number)
    } catch (error) {
      showToast(error.message || '部门范围加载失败', 'error')
    }
  }

  async function saveDepartmentScope(departmentIds) {
    if (!selectedScopeUserId.value) return
    try {
      const data = await api.domains.performance.replacePerformanceDepartmentScopes(
        selectedScopeUserId.value,
        departmentIds.map(Number),
      )
      selectedDepartmentIds.value = (data.department_ids || []).map(Number)
      showToast('部门数据范围已保存，用户角色和绩效动作权限未改变')
    } catch (error) {
      showToast(error.message || '部门范围保存失败', 'error')
    }
  }

  async function initPerformancePage() {
    loading.value = true
    try {
      await Promise.all([loadRules(), loadOverview()])
      await refreshFormalResults()
    } catch (error) {
      showToast(error.message || '绩效页面加载失败', 'error')
    } finally {
      loading.value = false
    }
  }

  return {
    yearMonth,
    warningLevel,
    positionId,
    search,
    scores,
    scoreResult,
    overview,
    plans,
    planDetail,
    summary,
    positionOptions,
    rules,
    loading,
    working,
    batches,
    selectedBatchId,
    batchDetail,
    comparison,
    exceptions,
    exceptionTotal,
    ruleVersions,
    targets,
    positions,
    scopeUsers,
    scopeDepartments,
    selectedScopeUserId,
    selectedDepartmentIds,
    loadScores,
    loadOverview,
    refreshFormalResults,
    loadPlans,
    loadPlanDetail,
    loadBatches,
    loadBatchDetail,
    createBatch,
    submitSupervisorReview,
    submitApproval,
    approveBatch,
    returnBatch,
    cancelBatch,
    createRevision,
    saveReview,
    loadComparison,
    loadExceptions,
    loadConfiguration,
    createTarget,
    approveTarget,
    createPlan,
    activatePlan,
    addPlanEvidence,
    requestPlanReassessment,
    reassessPlan,
    loadScopeSupport,
    loadDepartmentScope,
    saveDepartmentScope,
    initPerformancePage,
  }
}
