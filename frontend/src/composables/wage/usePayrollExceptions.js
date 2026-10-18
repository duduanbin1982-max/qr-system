import { computed, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function usePayrollExceptions() {
  const now = new Date()

  const month = ref(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`)

  const status = ref('')

  const items = ref([])

  const loading = ref(false)

  const working = ref(false)

  const editingId = ref(null)

  const form = ref({ unitPrice:'', reworkPercent:'', reason:'' })

  const canPrepare = computed(() => can('wages:prepare'))

  const canApprove = computed(() => can('wages:approve'))

  const parsed = new Map()

  const labels = { missing_route:'缺少工艺路线',missing_price:'缺少有效工价',zero_price:'工价为零',overlapping_price:'工价区间重叠',missing_rework_rate:'缺少返工倍率',invalid_amount:'数量或金额无效' }

  const statuses = { pending:'待处理',proposed:'待审批',approved:'已批准',rejected:'已驳回' }

  function snapshot(item) {
    if (!parsed.has(item.id)) { try { parsed.set(item.id, JSON.parse(item.snapshot_json || '{}')) } catch (_) { parsed.set(item.id, {}) } }
    return parsed.get(item.id)
  }

  function exceptionLabel(value) { return labels[value] || value }

  function statusLabel(value) { return statuses[value] || value }

  function price(value) { return `¥${(Number(value)/10000).toFixed(4)}` }

  function rate(value) { return `${(Number(value)/100).toFixed(2)}%` }

  async function load() {
    loading.value = true; parsed.clear()
    try { const data = await api.domains.wages.listPayrollExceptions({ payroll_month:month.value,status:status.value }); items.value=data.exceptions||[] }
    catch (error) { showToast(error.message || '异常队列加载失败','error') }
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
    try { await api.domains.wages.approvePayrollException(item.id); showToast('异常方案已批准'); await load() }
    catch (error) { showToast(error.message || '批准失败','error') }
    finally { working.value=false }
  }

  onMounted(load)

  return {
    now,
    month,
    status,
    items,
    loading,
    working,
    editingId,
    form,
    canPrepare,
    canApprove,
    parsed,
    labels,
    statuses,
    snapshot,
    exceptionLabel,
    statusLabel,
    price,
    rate,
    load,
    edit,
    propose,
    approve
  }
}
