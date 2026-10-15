import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WorkTimeAuditPanel from '@/views/work-time/WorkTimeAuditPanel.vue'
import WorkTimeRecordsPanel from '@/views/work-time/WorkTimeRecordsPanel.vue'
import WorkTimeStandardsPanel from '@/views/work-time/WorkTimeStandardsPanel.vue'
import WorkTimeReviewModal from '@/views/work-time/WorkTimeReviewModal.vue'
import WorkTimePage from '@/views/WorkTimePage.vue'

const mocks = vi.hoisted(() => ({ workTime: {}, orders: {}, routes: {}, processes: {}, users: {}, toast: vi.fn() }))
vi.mock('@/lib/api.js', () => ({ api: { domains: { workTime: mocks.workTime, orders: mocks.orders, processRoutes: mocks.routes, processes: mocks.processes, users: mocks.users } } }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))
const wrappers = []
const render = (component, options) => { const wrapper = mount(component, options); wrappers.push(wrapper); return wrapper }
const state = wrapper => wrapper.vm.$.setupState
beforeEach(() => {
  localStorage.clear()
  mocks.toast.mockReset()
  for (const name of ['listWorkTimeRecords', 'listWorkTimeStandards', 'listWorkTimeStandardRoutes', 'createWorkTimeRecord', 'saveRouteWorkTimeStandards', 'reviewWorkTimeRecord', 'workTimeStats']) mocks.workTime[name] = vi.fn().mockResolvedValue({})
  mocks.orders.listOrders = vi.fn().mockResolvedValue({ orders: [] })
  mocks.routes.listProcessRoutes = vi.fn().mockResolvedValue({ routes: [] })
  mocks.processes.listProcesses = vi.fn().mockResolvedValue({ processes: [] })
  mocks.users.listUsers = vi.fn().mockResolvedValue({ users: [] })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('Task 2D work-time Vue consumers', () => {
  it('keeps audit filters reactive, the 80 percent boundary and exposed review events', async () => {
    const rows = [{ id: 1, standard_minutes: 79, effective_minutes: 100 }, { id: 2, standard_minutes: 80, effective_minutes: 100 }, { id: 3, standard_minutes: 0, effective_minutes: 100 }]
    mocks.workTime.listWorkTimeRecords.mockResolvedValue({ items: rows })
    const wrapper = render(WorkTimeAuditPanel, { props: { keyword: '旧订单' } })
    await wrapper.setProps({ keyword: '新订单' })
    const vm = state(wrapper)
    Object.assign(vm.auditFilters, { process_id: 7, date_from: '2026-09-01', date_to: '2026-09-30' })
    vm.auditMode = 'low_efficiency'
    await wrapper.vm.load()
    expect(mocks.workTime.listWorkTimeRecords).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: '新订单', review_status: 'pending', process_id: 7, date_from: '2026-09-01', date_to: '2026-09-30', limit: 200 }))
    expect(vm.visibleRecords.map(row => row.id)).toEqual([1])
    await wrapper.find('tbody button').trigger('click')
    expect(wrapper.emitted('review')[0][0].id).toBe(1)
    mocks.workTime.listWorkTimeRecords.mockRejectedValue(new Error('查询失败'))
    await expect(wrapper.vm.load()).rejects.toThrow('查询失败')
    expect(vm.records).toHaveLength(3)
    expect(vm.isLoading).toBe(false)
  })

  it('keeps order process constraints, standard lookup and missing-standard fallback', async () => {
    const wrapper = render(WorkTimeRecordsPanel, { props: { processes: [{ id: 9, name: '通用' }] } })
    await wrapper.vm.openRecord()
    const vm = state(wrapper)
    vm.orderOptions = [{ id: 2, order_no: '26090101', route_id: 8, processes: [{ process_id: 7, process_name: '焊接' }] }]
    vm.recordForm.order_id = 2; vm.recordForm.process_id = 9
    await vm.selectOrderById()
    expect(vm.recordForm.process_id).toBe('')
    expect(vm.availableProcesses[0].process_id).toBe(7)
    vm.recordForm.process_id = 7
    mocks.workTime.listWorkTimeStandards.mockResolvedValue({ items: [{ id: 3, standard_minutes_per_unit: 5, setup_minutes: 2 }] })
    await vm.handleProcessChange()
    expect(mocks.workTime.listWorkTimeStandards).toHaveBeenCalledWith({ route_id: 8, process_id: 7, status: 'active', limit: 1 })
    expect(vm.standardStatus.text).toContain('单件 5 分')
    mocks.workTime.listWorkTimeStandards.mockRejectedValue(new Error('工时不可用'))
    await vm.handleProcessChange()
    expect(vm.standardStatus.text).toContain('缺少该路线工序标准工时')
    expect(vm.standardChecking).toBe(false)
  })

  it('keeps failed record edits open, then emits changed only after successful save', async () => {
    const wrapper = render(WorkTimeRecordsPanel, { props: { keyword: '旧' } })
    await wrapper.vm.openRecord()
    await wrapper.setProps({ keyword: '新', processes: [{ id: 8, name: '下料' }] })
    const vm = state(wrapper)
    Object.assign(vm.recordForm, { order_id: 2, process_id: 8, quantity: 3, user_id: 1000 })
    mocks.workTime.createWorkTimeRecord.mockRejectedValueOnce(new Error('报工已变化'))
    await vm.saveRecord()
    expect(vm.showRecordModal).toBe(true)
    expect(vm.isSaving).toBe(false)
    expect(wrapper.emitted('changed')).toBeUndefined()
    expect(mocks.toast).toHaveBeenCalledWith('报工已变化', 'error')
    await vm.saveRecord()
    expect(mocks.workTime.createWorkTimeRecord).toHaveBeenLastCalledWith(expect.objectContaining({ order_id: 2, process_id: 8, quantity: 3, user_id: 1000 }))
    expect(mocks.workTime.listWorkTimeRecords).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: '新', limit: 200 }))
    expect(vm.showRecordModal).toBe(false)
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('keeps version-group counts, scope and historical edit protection', async () => {
    const group = { route_id: 8, route_version_id: 81, route_version: 1, is_current_version: false, route_version_status: 'published', items: [{ id: 1, process_id: 7, status: 'active' }, { process_id: 8 }, { id: 2, process_id: 9, status: 'inactive' }] }
    mocks.workTime.listWorkTimeStandardRoutes.mockResolvedValue({ route_groups: [group] })
    const wrapper = render(WorkTimeStandardsPanel)
    const vm = state(wrapper)
    vm.includeHistory = true
    await wrapper.vm.load()
    expect(vm.standardOverview).toEqual({ total: 3, configured: 2, unconfigured: 1, active: 1, inactive: 1 })
    vm.setStandardScope('unconfigured')
    expect(vm.visibleStandardItemCount).toBe(1)
    expect(vm.standardGroups[0].items[0].process_id).toBe(8)
    await wrapper.vm.openStandardGroup(group)
    expect(vm.showStandardModal).toBe(false)
    expect(mocks.toast).toHaveBeenCalledWith('历史路线版本仅供审计查看，不能直接编辑', 'error')
    expect(mocks.workTime.listWorkTimeStandardRoutes).toHaveBeenCalledWith(expect.objectContaining({ include_history: true, limit: 200 }))
  })

  it('keeps route props live and requires an exact version and valid standard before saving', async () => {
    const wrapper = render(WorkTimeStandardsPanel, { props: { processRoutes: [] } })
    const vm = state(wrapper)
    await wrapper.setProps({ processRoutes: [{ id: 8, processes: [{ process_id: 7, process_name: '焊接', seq_order: 0 }] }] })
    vm.standardForm = { route_id: 8, effective_from: '2026-09-01' }
    await vm.buildStandardRows(8, [])
    expect(vm.standardRows[0].process_id).toBe(7)
    await vm.saveStandard()
    expect(mocks.workTime.saveRouteWorkTimeStandards).not.toHaveBeenCalled()
    vm.standardRows[0].standard_minutes_per_unit = 5
    await vm.saveStandard()
    expect(mocks.toast).toHaveBeenLastCalledWith('必须选择具体路线版本后才能保存工时', 'error')
    Object.assign(vm.standardForm, { route_version_id: 81 })
    Object.assign(vm.standardRows[0], { route_version_id: 81, process_version_id: 71, setup_minutes: 2, difficulty_factor: 1.2 })
    await vm.saveStandard()
    expect(mocks.workTime.saveRouteWorkTimeStandards).toHaveBeenCalledWith(expect.objectContaining({ route_id: 8, route_version_id: 81, effective_from: '2026-09-01', items: [expect.objectContaining({ process_id: 7, route_version_id: 81, process_version_id: 71, standard_minutes_per_unit: 5, setup_minutes: 2, difficulty_factor: 1.2, status: 'active' })] }))
    expect(wrapper.emitted('changed')).toHaveLength(1)
    expect(vm.isSaving).toBe(false)
  })

  it('rehydrates review on replacement and reopen and does not emit success on failure', async () => {
    const wrapper = render(WorkTimeReviewModal, { props: { modelValue: true, record: { id: 1, actual_minutes: 5 } } })
    const vm = state(wrapper)
    vm.reviewForm.review_note = '未提交'
    await wrapper.setProps({ record: { id: 2, actual_minutes: 8, review_status: 'rejected', review_note: '原记录' } })
    expect(vm.reviewForm).toEqual(expect.objectContaining({ id: 2, effective_minutes: 8, review_status: 'rejected', review_note: '原记录' }))
    await wrapper.setProps({ modelValue: false })
    vm.reviewForm.review_note = '修改'
    await wrapper.setProps({ modelValue: true })
    expect(vm.reviewForm.review_note).toBe('原记录')
    mocks.workTime.reviewWorkTimeRecord.mockRejectedValue(new Error('审核权限不足'))
    await vm.saveReview()
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(mocks.toast).toHaveBeenCalledWith('审核权限不足', 'error')
  })

  it('connects parent refs, active panel queries, primary actions and saved reviews', async () => {
    mocks.routes.listProcessRoutes.mockResolvedValue({ routes: [{ id: 8 }] })
    mocks.workTime.workTimeStats.mockResolvedValue({ total: 12 })
    const wrapper = render(WorkTimePage)
    await flushPromises()
    const vm = state(wrapper)
    expect(vm.processRoutes).toEqual([{ id: 8 }])
    expect(vm.stats.total).toBe(12)
    expect(mocks.workTime.listWorkTimeStandardRoutes).toHaveBeenCalled()
    await vm.switchTab('records')
    expect(localStorage.getItem('workTimeTab')).toBe('records')
    expect(mocks.workTime.listWorkTimeRecords).toHaveBeenCalled()
    vm.openPrimaryAction()
    await flushPromises()
    expect(state(wrapper.findComponent(WorkTimeRecordsPanel)).showRecordModal).toBe(true)
    vm.openReview({ id: 9, actual_minutes: 5 })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '保存审核').trigger('click')
    await flushPromises()
    expect(mocks.workTime.reviewWorkTimeRecord).toHaveBeenCalledWith(9, expect.objectContaining({ id: 9, effective_minutes: 5 }))
    expect(vm.showReviewModal).toBe(false)
  })
})
