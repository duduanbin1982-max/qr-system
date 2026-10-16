import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProcessQualityTaskDisposal from '@/components/ProcessQualityTaskDisposal.vue'
import ProcessQualityEvaluationPage from '@/views/ProcessQualityEvaluationPage.vue'
import QualityManagementPage from '@/views/QualityManagementPage.vue'
import InspectionList from '@/views/InspectionList.vue'
import ReworkList from '@/views/ReworkList.vue'

const mocks = vi.hoisted(() => ({ permissions: new Set(), evaluations: {}, management: {}, quality: {}, rework: {}, users: {}, processes: {}, toast: vi.fn() }))
vi.mock('@/lib/api.js', () => ({ api: { domains: { processQualityEvaluations: mocks.evaluations, qualityManagement: mocks.management, quality: mocks.quality, rework: mocks.rework, users: mocks.users, processes: mocks.processes } } }))
vi.mock('@/lib/auth.js', () => ({ can: permission => mocks.permissions.has(permission) }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))
const wrappers = []
const render = (component, options) => { const wrapper = mount(component, options); wrappers.push(wrapper); return wrapper }
const state = wrapper => wrapper.vm.$.setupState
beforeEach(() => {
  localStorage.clear(); mocks.permissions = reactive(new Set()); mocks.toast.mockReset()
  for (const name of ['qualityEvaluationTaskDisposalSummary', 'qualityEvaluationTasks', 'qualityEvaluationTaskAudits', 'previewQualityEvaluationTaskWaiver', 'waiveQualityEvaluationTasks', 'qualityEvaluationRecords', 'qualityEvaluationAppeals', 'qualityEvaluationStats', 'reviewQualityEvaluation', 'reviewQualityEvaluationAppeal']) mocks.evaluations[name] = vi.fn().mockResolvedValue({})
  for (const name of ['qualityReferences', 'qualityDashboard', 'qualityStandards', 'qualityNcr', 'disposeQualityNcr', 'qualityTask', 'inspectQualityTask', 'qualityTasks']) mocks.management[name] = vi.fn().mockResolvedValue({})
  for (const name of ['listInspections', 'inspectionStats', 'deleteInspection']) mocks.quality[name] = vi.fn().mockResolvedValue({})
  mocks.rework.listRework = vi.fn().mockResolvedValue({ ok: true, items: [], total: 0 })
  mocks.rework.reworkStats = vi.fn().mockResolvedValue({ ok: true })
  mocks.rework.batchCompleteRework = vi.fn().mockResolvedValue({ ok: true, completed: 2 })
  mocks.users.listUsers = vi.fn().mockResolvedValue({ users: [] })
  mocks.processes.listProcesses = vi.fn().mockResolvedValue({ processes: [] })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('Task 2D quality Vue consumers', () => {
  it('keeps live waiver policy, deduplicated selection, preview and reason validation', async () => {
    const historical = { id: 1, status: 'pending', order_status: 'completed' }
    const live = { id: 2, status: 'pending', order_status: 'producing' }
    mocks.evaluations.qualityEvaluationTaskDisposalSummary.mockResolvedValue({ waiver_policy: { can_waive_live: false } })
    mocks.evaluations.qualityEvaluationTasks.mockResolvedValue({ items: [historical, live], total: 2 })
    mocks.evaluations.previewQualityEvaluationTaskWaiver.mockResolvedValue({ waiver_scope: 'historical', can_submit: true, orders: [], warnings: [] })
    const wrapper = render(ProcessQualityTaskDisposal)
    await wrapper.vm.reload()
    const vm = state(wrapper)
    expect(vm.disposableTasks.map(task => task.id)).toEqual([1])
    vm.toggleTask(1, true); vm.toggleTask(1, true)
    expect(vm.selectedTaskIds).toEqual([1])
    await vm.openWaiver([1, 1])
    expect(mocks.evaluations.previewQualityEvaluationTaskWaiver).toHaveBeenCalledWith({ task_ids: [1] })
    await vm.saveWaiver()
    expect(mocks.evaluations.waiveQualityEvaluationTasks).not.toHaveBeenCalled()
    Object.assign(vm.waiverForm, { reasonCode: 'historical_evidence', reason: '  留痕  ' })
    mocks.evaluations.waiveQualityEvaluationTasks.mockRejectedValueOnce(new Error('证据过期'))
    await vm.saveWaiver()
    expect(vm.showWaiver).toBe(true)
    expect(vm.waiving).toBe(false)
    expect(wrapper.emitted('waived')).toBeUndefined()
    await vm.saveWaiver()
    expect(mocks.evaluations.waiveQualityEvaluationTasks).toHaveBeenLastCalledWith({ task_ids: [1], reason_code: 'historical_evidence', reason: '留痕' })
    expect(wrapper.emitted('waived')).toHaveLength(1)
  })

  it('requires a submittable live preview and ten-character reason for an order waiver', async () => {
    mocks.evaluations.previewQualityEvaluationTaskWaiver.mockResolvedValue({ waiver_scope: 'live', can_submit: false, orders: [], warnings: [] })
    const wrapper = render(ProcessQualityTaskDisposal)
    const vm = state(wrapper)
    await vm.openOrderWaiver({ order_id: 9, order_no: '26090101' })
    expect(mocks.evaluations.previewQualityEvaluationTaskWaiver).toHaveBeenCalledWith({ order_id: 9, required_only: true })
    Object.assign(vm.waiverForm, { reasonCode: 'live_exception', reason: '生产异常' })
    await vm.saveWaiver()
    expect(mocks.evaluations.waiveQualityEvaluationTasks).not.toHaveBeenCalled()
    vm.waiverPreview.can_submit = true
    await vm.saveWaiver()
    expect(mocks.evaluations.waiveQualityEvaluationTasks).not.toHaveBeenCalled()
    vm.waiverForm.reason = '  生产中订单已有独立核验证据  '
    await vm.saveWaiver()
    expect(mocks.evaluations.waiveQualityEvaluationTasks).toHaveBeenCalledWith({ order_id: 9, required_only: true, reason_code: 'live_exception', reason: '生产中订单已有独立核验证据' })
  })

  it('keeps disposal keyword reactive, retries out-of-range pages and prunes invisible selection', async () => {
    mocks.evaluations.qualityEvaluationTasks.mockResolvedValue({ items: [{ id: 2, status: 'pending' }], total: 1 })
    const wrapper = render(ProcessQualityTaskDisposal, { props: { keyword: '旧' } })
    await wrapper.setProps({ keyword: '新' })
    const vm = state(wrapper)
    vm.page = 3; vm.selectedTaskIds = [1, 2]
    await wrapper.vm.reload()
    expect(mocks.evaluations.qualityEvaluationTasks.mock.calls.map(call => call[0].page)).toEqual([3, 1])
    expect(mocks.evaluations.qualityEvaluationTasks).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: '新', page: 1, per_page: 50, scope: 'all', status: 'pending' }))
    expect(vm.selectedTaskIds).toEqual([2])
    vm.status = 'audit'
    await vm.changeStatus()
    expect(mocks.evaluations.qualityEvaluationTaskAudits).toHaveBeenCalledWith({ keyword: '新', page: 1, per_page: 50 })
    expect(vm.selectedTaskIds).toEqual([])
  })

  it.each([false, true])('only requests quality statistics with permission (%s)', async withPermission => {
    if (withPermission) mocks.permissions.add('process_quality_evaluation:stats')
    mocks.evaluations.qualityEvaluationStats.mockResolvedValue({ summary: { total: 9 } })
    const wrapper = render(ProcessQualityEvaluationPage)
    await flushPromises()
    const vm = state(wrapper)
    expect(vm.visibleTabs.some(tab => tab.key === 'stats')).toBe(withPermission)
    expect(mocks.evaluations.qualityEvaluationStats).toHaveBeenCalledTimes(withPermission ? 1 : 0)
    expect(vm.statsSummary).toEqual(withPermission ? { total: 9 } : {})

    await vm.switchTab('records')
    expect(mocks.evaluations.qualityEvaluationStats).toHaveBeenCalledTimes(withPermission ? 2 : 0)
    vm.yearMonth = '2026-10'
    await vm.loadActive()
    expect(mocks.evaluations.qualityEvaluationStats).toHaveBeenCalledTimes(withPermission ? 3 : 0)
    if (withPermission) {
      expect(mocks.evaluations.qualityEvaluationStats).toHaveBeenLastCalledWith({ year_month: '2026-10' })
    }

    mocks.permissions.delete('process_quality_evaluation:stats')
    await vm.loadActive()
    expect(mocks.evaluations.qualityEvaluationStats).toHaveBeenCalledTimes(withPermission ? 3 : 0)
    expect(vm.visibleTabs.some(tab => tab.key === 'stats')).toBe(false)
  })

  it('keeps quality-evaluation permission tabs, review commands and failure state', async () => {
    localStorage.setItem('processQualityEvaluationTab', 'rules')
    const reader = render(ProcessQualityEvaluationPage)
    await flushPromises()
    expect(state(reader).activeTab).toBe('tasks')
    expect(state(reader).visibleTabs.map(tab => tab.key)).toEqual(['tasks', 'records'])
    mocks.permissions.add('process_quality_evaluation:review')
    const reviewer = render(ProcessQualityEvaluationPage)
    await flushPromises()
    const vm = state(reviewer)
    expect(vm.visibleTabs.map(tab => tab.key)).toContain('appeals')
    vm.keyword = '焊接'; vm.yearMonth = '2026-09'
    await vm.switchTab('review')
    expect(mocks.evaluations.qualityEvaluationRecords).toHaveBeenLastCalledWith({ year_month: '2026-09', status: 'pending_verification', keyword: '焊接', page: 1, per_page: 50 })
    vm.openReview('appeal', { id: 8 }, 'accepted')
    await vm.saveReview()
    expect(mocks.evaluations.reviewQualityEvaluationAppeal).not.toHaveBeenCalled()
    vm.reviewForm.note = '独立核验'
    mocks.evaluations.reviewQualityEvaluationAppeal.mockRejectedValueOnce(new Error('复核冲突'))
    await vm.saveReview()
    expect(vm.showReview).toBe(true)
    expect(mocks.toast).toHaveBeenCalledWith('复核冲突', 'error')
    await vm.saveReview()
    expect(mocks.evaluations.reviewQualityEvaluationAppeal).toHaveBeenLastCalledWith(8, { status: 'accepted', note: '独立核验' })
    expect(mocks.evaluations.reviewQualityEvaluation).not.toHaveBeenCalled()
    expect(vm.showReview).toBe(false)
  })

  it('keeps disposition permission, tab reset, payload and error dialog', async () => {
    const reader = render(QualityManagementPage)
    await flushPromises()
    await state(reader).switchTab('ncr')
    expect(state(reader).primaryLabel).toBe('')
    mocks.permissions.add('quality:disposition')
    const wrapper = render(QualityManagementPage)
    await flushPromises()
    const vm = state(wrapper)
    vm.keyword = '旧'; vm.filterStatus = 'closed'
    await vm.switchTab('ncr')
    expect(vm.primaryLabel).toBe('新增质量异常')
    expect(mocks.management.qualityNcr).toHaveBeenLastCalledWith({ keyword: '', status: '', limit: 500 })
    vm.openDisposition({ id: 2, process_id: 7, owner_id: 1000 })
    Object.assign(vm.dispositionForm, { disposition: 'scrap', root_cause: '材质', note: '审批依据' })
    mocks.management.disposeQualityNcr.mockRejectedValueOnce(new Error('权限已撤销'))
    await vm.saveDisposition()
    expect(vm.showDisposition).toBe(true)
    expect(mocks.toast).toHaveBeenCalledWith('权限已撤销', 'error')
    await vm.saveDisposition()
    expect(mocks.management.disposeQualityNcr).toHaveBeenLastCalledWith(2, expect.objectContaining({ disposition: 'scrap', owner_id: 1000, responsible_process_id: 7, root_cause: '材质', note: '审批依据' }))
    expect(vm.showDisposition).toBe(false)
  })

  it('keeps inspection filters, export and delete confirmation with statistics refresh', async () => {
    mocks.quality.listInspections.mockResolvedValue({ items: [{ id: 2, result: 'rework' }] })
    const wrapper = render(InspectionList)
    await flushPromises()
    const vm = state(wrapper)
    vm.keyword = 'A&B'; vm.filterResult = 'rework'
    await vm.load()
    expect(mocks.quality.listInspections).toHaveBeenLastCalledWith({ keyword: 'A&B', result: 'rework' })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    vm.exportExcel()
    expect(open).toHaveBeenCalledWith('/api/quality/inspections/export?search=A%26B&result=rework', '_blank')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await vm.del({ id: 2 })
    expect(mocks.quality.deleteInspection).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    await vm.del({ id: 2 })
    expect(mocks.quality.deleteInspection).toHaveBeenCalledWith(2)
    expect(mocks.quality.inspectionStats).toHaveBeenCalledTimes(2)
  })

  it('rejects stale rework results, inherits export filters and retains partial batch errors', async () => {
    const wrapper = render(ReworkList)
    await flushPromises()
    const vm = state(wrapper)
    let resolveOld
    mocks.rework.listRework.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const old = vm.load(1)
    vm.search = '新订单'; vm.filterWorker = 1000; vm.filterProcess = 7; vm.dateFrom = '2026-09-01'; vm.dateTo = '2026-09-30'
    mocks.rework.listRework.mockResolvedValue({ ok: true, items: [{ id: 2, status: 'pending' }], total: 1 })
    await vm.load(2)
    resolveOld({ ok: true, items: [{ id: 1 }], total: 100 })
    await old
    expect(vm.items.map(row => row.id)).toEqual([2])
    expect(vm.total).toBe(1)
    expect(vm.loading).toBe(false)
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    vm.exportData()
    const url = new URL(open.mock.calls[0][0], 'http://localhost')
    expect(Object.fromEntries(url.searchParams)).toEqual({ status: 'pending', search: '新订单', from: '2026-09-01', to: '2026-09-30', worker_id: '1000', process_id: '7' })
    vm.selectedIds = [2, 3]; vm.openBatchComplete(); vm.batchReason = '返修复检'
    mocks.rework.batchCompleteRework.mockResolvedValue({ ok: true, completed: 1, errors: [{ id: 3, error: '已处置' }] })
    await vm.doBatchComplete()
    expect(mocks.rework.batchCompleteRework).toHaveBeenCalledWith({ ids: [2, 3], reason: '返修复检', result: 'ok', result_remark: '' })
    expect(vm.showBatchModal).toBe(true)
    expect(vm.batchErrors).toHaveLength(1)
    expect(vm.selectedIds).toEqual([])
    expect(vm.batchSubmitting).toBe(false)
    expect(mocks.toast).toHaveBeenCalledWith('已完成 1 条，1 条失败', 'warn')
  })
})
