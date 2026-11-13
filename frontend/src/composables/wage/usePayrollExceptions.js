import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function usePayrollExceptions() {
  const now = new Date()

  const month = ref(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`)

  const status = ref('')

  const items = ref([])

  const auditFindings = ref([])

  const auditStatus = ref('open')

  const includeAuditHistory = ref(false)

  const auditResolutions = ref({})

  const loading = ref(false)

  const working = ref(false)

  const editingId = ref(null)

  const form = ref({ unitPrice:'', reworkPercent:'', reason:'' })

  const canPrepare = computed(() => can('wages:prepare'))

  const canApprove = computed(() => can('wages:approve'))

  const parsed = new Map()

  const labels = { missing_route:'缺少工艺路线',missing_price:'缺少有效工价',zero_price:'工价为零',overlapping_price:'工价区间重叠',missing_rework_rate:'缺少返工倍率',invalid_amount:'数量或金额无效' }

  const statuses = { pending:'待处理',proposed:'待审批',approved:'已批准',rejected:'已驳回' }

  const findingLabels = {
    pending_approval_work:'报工待审批',
    duplicate_serial_work:'序列号重复报工',
    duplicate_work_candidate:'疑似重复报工',
    cross_period_work:'跨工资期间报工',
    high_payroll_deviation:'工资偏差较大',
  }

  const findingStatuses = { open:'待处理',resolved:'已复核',superseded:'已被重算取代' }

  function snapshot(item) {
    if (!parsed.has(item.id)) { try { parsed.set(item.id, JSON.parse(item.snapshot_json || '{}')) } catch (_) { parsed.set(item.id, {}) } }
    return parsed.get(item.id)
  }

  function exceptionLabel(value) { return labels[value] || value }

  function statusLabel(value) { return statuses[value] || value }

  function findingLabel(value) { return findingLabels[value] || value }

  function findingStatusLabel(value) { return findingStatuses[value] || value }

  function findingSnapshot(item) {
    try { return JSON.parse(item.snapshot_json || '{}') } catch (_) { return {} }
  }

  function findingSubject(item) {
    const snapshot = findingSnapshot(item)
    const details = snapshot.work_record || {}
    if (item.subject_type === 'employee') {
      return [snapshot.employee_name, snapshot.employee_no].filter(Boolean).join(' / ') || ('员工 #' + item.subject_id)
    }
    return [details.employee_name, details.order_no, details.process_name, '报工 #' + item.subject_id]
      .filter(Boolean).join(' · ')
  }

  function findingEvidence(item) {
    const snapshot = findingSnapshot(item)
    const work = snapshot.work_record || {}
    const records = snapshot.work_record_ids || []
    if (item.finding_type === 'pending_approval_work') {
      return [
        '状态：' + (work.status || '-'),
        '录入时间：' + (work.created_at || '-'),
        '批次截止：' + (snapshot.cutoff_at || '-'),
        '数量：' + (work.quantity ?? '-'),
      ]
    }
    if (item.finding_type === 'duplicate_serial_work') {
      return [
        '序列号：' + (snapshot.serial_no || '-'),
        '重复记录：' + (records.join(', ') || '-'),
        '订单/工序：' + (snapshot.order_no || snapshot.order_id || '-') + ' / '
          + (snapshot.process_name || snapshot.process_id || '-'),
      ]
    }
    if (item.finding_type === 'duplicate_work_candidate') {
      return [
        '精确到秒的实际时间：' + (snapshot.effective_at || '-'),
        '员工/订单/工序：' + (work.employee_name || '-') + ' / '
          + (work.order_no || '-') + ' / ' + (work.process_name || '-'),
        '类型/数量：' + (snapshot.work_type || '-') + ' / ' + (snapshot.quantity ?? '-'),
        '候选记录：' + (records.join(', ') || '-'),
      ]
    }
    if (item.finding_type === 'cross_period_work') {
      return [
        '实际完成：' + (work.actual_completed_at || '-'),
        '录入时间：' + (work.created_at || '-'),
        '实际归属/录入归属：' + (snapshot.actual_payroll_month || '-') + ' / '
          + (snapshot.recorded_payroll_month || '-'),
        '归属日界：' + (snapshot.boundary_hour ?? 7) + ':00',
      ]
    }
    if (item.finding_type === 'high_payroll_deviation') {
      const history = (snapshot.historical_periods || [])
        .map(row => row.payroll_month + ' ¥' + (Number(row.payable_wage_cents) / 100).toFixed(2))
        .join('、')
      const median = Number(snapshot.historical_median_twice_cents) / 200
      const difference = Number(snapshot.difference_twice_cents) / 200
      return [
        '本期：¥' + (Number(snapshot.current_payable_cents) / 100).toFixed(2),
        '最近可比期间：' + (history || '-'),
        '历史中位数：¥' + median.toFixed(2) + '；差额：¥' + difference.toFixed(2),
        '门槛：偏差至少 ' + (Number(snapshot.relative_threshold_basis_points) / 100)
          + '% 且不少于 ¥' + (Number(snapshot.absolute_threshold_cents) / 100).toFixed(2),
      ]
    }
    return []
  }

  function price(value) { return `¥${(Number(value)/10000).toFixed(4)}` }

  function rate(value) { return `${(Number(value)/100).toFixed(2)}%` }

  async function load() {
    loading.value = true; parsed.clear()
    try {
      const [data, auditData] = await Promise.all([
        api.domains.wages.listPayrollExceptions({ payroll_month:month.value,status:status.value }),
        api.domains.wages.listPayrollAuditFindings({
          payroll_month:month.value,
          status:includeAuditHistory.value ? '' : auditStatus.value,
          include_history:includeAuditHistory.value ? 1 : undefined,
        }),
      ])
      items.value=data.exceptions||[]
      auditFindings.value=auditData.audit_findings||[]
      auditResolutions.value={}
    }
    catch (error) { showToast(error.message || '工资异常队列加载失败','error') }
    finally { loading.value=false }
  }

  function edit(item) {
    editingId.value=item.id
    form.value={
      unitPrice:item.proposed_price_micros==null?'':Number(item.proposed_price_micros)/10000,
      reworkPercent:item.proposed_rework_rate_basis_points==null?'':Number(item.proposed_rework_rate_basis_points)/100,
      reason:item.resolution_reason||'',
    }
  }

  async function propose(item) {
    if (!form.value.reason.trim()) { showToast('请填写核定原因','error'); return }
    const data={ resolution_reason:form.value.reason.trim() }
    if (form.value.unitPrice !== '') data.proposed_price_micros=Math.round(Number(form.value.unitPrice)*10000)
    if (snapshot(item).type==='rework' && form.value.reworkPercent !== '') data.proposed_rework_rate_basis_points=Math.round(Number(form.value.reworkPercent)*100)
    working.value=true
    try { await api.domains.wages.proposePayrollException(item.id,data); editingId.value=null; showToast('异常处理方案已提交'); await load() }
    catch (error) { showToast(error.message || '提交失败','error') }
    finally { working.value=false }
  }

  async function approve(item) {
    if (!window.confirm('批准后将形成不可变的报工价格解析，是否继续？')) return
    working.value=true
    try { await api.domains.wages.approvePayrollException(item.id); showToast('异常方案已批准，请返回台账重算'); await load() }
    catch (error) { showToast(error.message || '批准失败','error') }
    finally { working.value=false }
  }

  async function resolveAuditFinding(item) {
    const reason=(auditResolutions.value[item.id]||'').trim()
    if (reason.length < 4) { showToast('请填写至少 4 个字的复核原因','error'); return }
    if (!window.confirm('此操作只记录人工复核结论，不会修改工资金额，是否继续？')) return
    const resolution_code = item.finding_type==='high_payroll_deviation'
      ? 'confirmed_variance'
      : 'confirmed_distinct_work'
    working.value=true
    try {
      await api.domains.wages.resolvePayrollAuditFinding(item.id,{
        resolution_code,
        resolution_reason:reason,
      })
      showToast('工资审计异常已记录复核结论')
      await load()
    }
    catch (error) { showToast(error.message || '审计异常复核失败','error') }
    finally { working.value=false }
  }

  onMounted(load)

  return {
    now,
    month,
    status,
    items,
    auditFindings,
    auditStatus,
    includeAuditHistory,
    auditResolutions,
    loading,
    working,
    editingId,
    form,
    canPrepare,
    canApprove,
    parsed,
    labels,
    statuses,
    findingLabels,
    findingStatuses,
    snapshot,
    exceptionLabel,
    statusLabel,
    findingLabel,
    findingStatusLabel,
    findingSnapshot,
    findingSubject,
    findingEvidence,
    price,
    rate,
    load,
    edit,
    propose,
    approve,
    resolveAuditFinding
  }
}
