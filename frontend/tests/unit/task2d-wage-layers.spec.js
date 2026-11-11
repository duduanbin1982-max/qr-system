import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdjustmentTab from '@/views/wage/AdjustmentTab.vue'
import MyPayrollTab from '@/views/wage/MyPayrollTab.vue'
import PayrollExceptionsTab from '@/views/wage/PayrollExceptionsTab.vue'
import PayrollLedgerTab from '@/views/wage/PayrollLedgerTab.vue'
import ProcessWageTab from '@/views/wage/ProcessWageTab.vue'
import HistoricalPriceConfirmationPanel from '@/components/wage/HistoricalPriceConfirmationPanel.vue'
import PriceVersionEditor from '@/components/wage/PriceVersionEditor.vue'
import PriceList from '@/views/PriceList.vue'
import WageList from '@/views/WageList.vue'

const mocks = vi.hoisted(() => ({ permissions: new Set(), auth: { user: { id: 17 } }, wages: {}, users: {}, pricing: {}, routes: {}, toast: vi.fn(), navigate: vi.fn(), router: {} }))
vi.mock('@/lib/api.js', () => ({ api: { domains: { wages: mocks.wages, users: mocks.users, pricing: mocks.pricing, processRoutes: mocks.routes } } }))
vi.mock('@/lib/auth.js', () => ({ auth: mocks.auth, can: permission => mocks.permissions.has(permission) }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))
vi.mock('@/lib/router.js', () => ({ router: reactive(mocks.router), navigate: mocks.navigate }))

const wrappers = []
function render(component, options) { const wrapper = mount(component, options); wrappers.push(wrapper); return wrapper }
const state = wrapper => wrapper.vm.$.setupState
const buttons = wrapper => wrapper.findAll('button').map(button => button.text())

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  mocks.permissions = new Set()
  mocks.auth.user = { id: 17 }
  mocks.router.page = 'structure-prices'
  mocks.router.params = {}
  for (const name of ['listPayrollAdjustments', 'createPayrollAdjustment', 'reversePayrollAdjustment', 'getMyPayroll', 'listPayrollExceptions', 'proposePayrollException', 'approvePayrollException', 'listPayrollBatches', 'createPayrollBatch', 'getPayrollBatch', 'submitPayrollBatch', 'lockPayrollBatch', 'confirmPayrollBatch', 'revisePayrollBatch', 'regeneratePayrollBatch', 'getRoutePriceVersionReference', 'listRoutePriceVersions', 'createHistoricalPriceManualDraft', 'voidHistoricalPriceManualDraft', 'approveHistoricalPriceManualDraft', 'createRoutePriceVersion', 'voidRoutePriceVersion']) mocks.wages[name] = vi.fn().mockResolvedValue({})
  mocks.users.listUsers = vi.fn().mockResolvedValue({ users: [{ id: 1, name: '在职' }, { id: 2, status: 'disabled' }] })
  mocks.routes.listProcessRoutes = vi.fn().mockResolvedValue({ routes: [{ id: 8, name: '路线', category: '结构件' }] })
  mocks.pricing.getRoutePricingDetail = vi.fn().mockResolvedValue({ steps: [{ process_id: 7, unit_price: 2 }] })
  mocks.pricing.getRoutePricingHistory = vi.fn().mockResolvedValue({ history: [{ id: 1 }] })
  mocks.pricing.saveRouteLevelPricing = vi.fn().mockResolvedValue({})
  mocks.toast.mockReset()
  mocks.navigate.mockReset()
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('Task 2D payroll permissions, totals and commands through Vue consumers', () => {
  it('keeps adjustment employee queries and entry controls behind prepare permission', async () => {
    const reader = render(AdjustmentTab)
    await flushPromises()
    expect(buttons(reader)).not.toContain('新增调整')
    expect(mocks.users.listUsers).not.toHaveBeenCalled()
    mocks.permissions.add('wages:prepare')
    const preparer = render(AdjustmentTab)
    await flushPromises()
    expect(buttons(preparer)).toContain('新增调整')
    expect(state(preparer).employees.map(employee => employee.id)).toEqual([1])
  })

  it('keeps reversal signs and validates adjustment fields before writing', async () => {
    mocks.permissions.add('wages:prepare')
    mocks.wages.listPayrollAdjustments.mockResolvedValue({ adjustments: [
      { id: 1, adjustment_type: 'bonus', amount_cents: 500 },
      { id: 2, reversal_of_id: 1, adjustment_type: 'bonus', amount_cents: 500 },
      { id: 3, adjustment_type: 'deduction', amount_cents: 100 },
    ] })
    const wrapper = render(AdjustmentTab)
    await flushPromises()
    const vm = state(wrapper)
    expect(vm.totals).toEqual({ bonus: 0, allowance: 0, deduction: 100, net: -100 })
    expect(wrapper.text()).toContain('-¥1.00')
    await vm.createAdjustment()
    expect(mocks.wages.createPayrollAdjustment).not.toHaveBeenCalled()
    vm.month = '2026-09'
    vm.form = { employeeId: '1', type: 'allowance', amount: '12.50', reason: '  班次补贴  ' }
    await vm.createAdjustment()
    expect(mocks.wages.createPayrollAdjustment).toHaveBeenCalledWith({
      employee_id: 1,
      payroll_month: '2026-09',
      adjustment_type: 'allowance',
      amount: '12.50',
      reason: '班次补贴',
      idempotency_key: expect.stringMatching(/^payroll-adjustment-ui:create:/),
    })
    expect(vm.form.employeeId).toBe('')
  })

  it('reuses adjustment and reversal idempotency keys after normalized uncertain retries', async () => {
    mocks.permissions.add('wages:prepare')
    mocks.wages.createPayrollAdjustment
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValueOnce({ id: 8, replayed: true })
    mocks.wages.reversePayrollAdjustment
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValueOnce({ id: 9, replayed: true })
    const wrapper = render(AdjustmentTab)
    await flushPromises()
    const vm = state(wrapper)
    vm.month = '2026-09'
    vm.form = { employeeId: '1', type: 'bonus', amount: '8.00', reason: '  夜班   奖励  ' }

    await vm.createAdjustment()
    vm.form.amount = '8'
    vm.form.reason = '夜班 奖励'
    await vm.createAdjustment()

    const firstCreate = mocks.wages.createPayrollAdjustment.mock.calls[0][0]
    const secondCreate = mocks.wages.createPayrollAdjustment.mock.calls[1][0]
    expect(firstCreate.reason).toBe('夜班 奖励')
    expect(secondCreate.reason).toBe('夜班 奖励')
    expect(secondCreate.idempotency_key).toBe(firstCreate.idempotency_key)
    expect(sessionStorage.getItem('payroll-adjustments:pending-command:17:create')).toBeNull()

    vi.spyOn(window, 'prompt')
      .mockReturnValueOnce('  原调整   错误  ')
      .mockReturnValueOnce('原调整 错误')
    const original = { id: 5 }
    await vm.reverse(original)
    await vm.reverse(original)

    const firstReverse = mocks.wages.reversePayrollAdjustment.mock.calls[0]
    const secondReverse = mocks.wages.reversePayrollAdjustment.mock.calls[1]
    expect(firstReverse[0]).toBe(5)
    expect(firstReverse[1]).toEqual({
      reason: '原调整 错误',
      idempotency_key: expect.stringMatching(/^payroll-adjustment-ui:reverse:/),
    })
    expect(secondReverse[1].idempotency_key).toBe(firstReverse[1].idempotency_key)
    expect(sessionStorage.getItem('payroll-adjustments:pending-command:17:reverse')).toBeNull()
  })

  it('keeps distinct uncertain create commands across a component remount', async () => {
    mocks.permissions.add('wages:prepare')
    mocks.wages.createPayrollAdjustment
      .mockRejectedValueOnce(new Error('第一条响应中断'))
      .mockRejectedValueOnce(new Error('第二条响应中断'))
      .mockResolvedValueOnce({ id: 18, replayed: true })
    const wrapper = render(AdjustmentTab)
    await flushPromises()
    const vm = state(wrapper)
    vm.month = '2026-10'
    vm.form = { employeeId: '1', type: 'bonus', amount: '8.00', reason: '夜班奖励' }
    await vm.createAdjustment()
    const firstKey = mocks.wages.createPayrollAdjustment.mock.calls[0][0].idempotency_key

    vm.form = { employeeId: '1', type: 'allowance', amount: '5.00', reason: '餐费补贴' }
    await vm.createAdjustment()
    const secondKey = mocks.wages.createPayrollAdjustment.mock.calls[1][0].idempotency_key
    expect(secondKey).not.toBe(firstKey)
    const storageKey = 'payroll-adjustments:pending-command:17:create'
    expect(new Map(JSON.parse(sessionStorage.getItem(storageKey))).size).toBe(2)

    wrapper.unmount()
    const remounted = render(AdjustmentTab)
    await flushPromises()
    const retry = state(remounted)
    retry.month = '2026-10'
    retry.form = { employeeId: '1', type: 'bonus', amount: '8.00', reason: '夜班奖励' }
    await retry.createAdjustment()

    expect(mocks.wages.createPayrollAdjustment.mock.calls[2][0].idempotency_key).toBe(firstKey)
    const remaining = new Map(JSON.parse(sessionStorage.getItem(storageKey)))
    expect([...remaining.values()]).toEqual([secondKey])
  })

  it('isolates pending adjustment commands by authenticated user', async () => {
    mocks.permissions.add('wages:prepare')
    mocks.wages.createPayrollAdjustment.mockRejectedValue(new Error('网络中断'))
    const firstUser = render(AdjustmentTab)
    await flushPromises()
    const first = state(firstUser)
    first.month = '2026-10'
    first.form = { employeeId: '1', type: 'bonus', amount: '6.00', reason: '用户隔离' }
    await first.createAdjustment()

    mocks.auth.user = { id: 23 }
    const secondUser = render(AdjustmentTab)
    await flushPromises()
    const second = state(secondUser)
    second.month = '2026-10'
    second.form = { employeeId: '1', type: 'bonus', amount: '6.00', reason: '用户隔离' }
    await second.createAdjustment()

    const firstKey = mocks.wages.createPayrollAdjustment.mock.calls[0][0].idempotency_key
    const secondKey = mocks.wages.createPayrollAdjustment.mock.calls[1][0].idempotency_key
    expect(secondKey).not.toBe(firstKey)
    expect(sessionStorage.getItem('payroll-adjustments:pending-command:17:create')).not.toBeNull()
    expect(sessionStorage.getItem('payroll-adjustments:pending-command:23:create')).not.toBeNull()
  })

  it('keeps the same in-memory idempotency key when session storage is unavailable', async () => {
    mocks.permissions.add('wages:prepare')
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    mocks.wages.createPayrollAdjustment
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValueOnce({ id: 28, replayed: true })
    const wrapper = render(AdjustmentTab)
    await flushPromises()
    const vm = state(wrapper)
    vm.month = '2026-10'
    vm.form = { employeeId: '1', type: 'bonus', amount: '7.00', reason: '存储受限' }

    await vm.createAdjustment()
    await vm.createAdjustment()

    const firstKey = mocks.wages.createPayrollAdjustment.mock.calls[0][0].idempotency_key
    expect(mocks.wages.createPayrollAdjustment.mock.calls[1][0].idempotency_key).toBe(firstKey)
  })

  it('keeps personal payroll month and preserves loaded lines after failure', async () => {
    mocks.wages.getMyPayroll.mockResolvedValue({ lines: [{ id: 4, payable_wage_cents: 2500 }] })
    const wrapper = render(MyPayrollTab)
    await flushPromises()
    const vm = state(wrapper)
    vm.month = '2026-08'
    mocks.wages.getMyPayroll.mockRejectedValue(new Error('工资不可用'))
    await vm.load()
    expect(mocks.wages.getMyPayroll).toHaveBeenLastCalledWith('2026-08')
    expect(vm.lines[0].id).toBe(4)
    expect(vm.loading).toBe(false)
    expect(mocks.toast).toHaveBeenCalledWith('工资不可用', 'error')
  })

  it('keeps payroll exception proposal units and required reason', async () => {
    const item = { id: 2, status: 'pending', snapshot_json: '{"type":"rework","order_no":"26090101"}' }
    mocks.permissions.add('wages:prepare')
    mocks.wages.listPayrollExceptions.mockResolvedValue({ exceptions: [item] })
    const wrapper = render(PayrollExceptionsTab)
    await flushPromises()
    expect(buttons(wrapper)).toContain('提出方案')
    expect(buttons(wrapper)).not.toContain('批准')
    const vm = state(wrapper)
    vm.edit(item)
    await vm.propose(item)
    expect(mocks.wages.proposePayrollException).not.toHaveBeenCalled()
    vm.form = { unitPrice: '12.3456', reworkPercent: '45.67', reason: '  凭证01  ' }
    await vm.propose(item)
    expect(mocks.wages.proposePayrollException).toHaveBeenCalledWith(2, { resolution_reason: '凭证01', proposed_price_micros: 123456, proposed_rework_rate_basis_points: 4567 })
  })

  it('keeps exception approval confirmation and write errors visible', async () => {
    mocks.permissions.add('wages:approve')
    const item = { id: 9, status: 'proposed', snapshot_json: 'bad json' }
    mocks.wages.listPayrollExceptions.mockResolvedValue({ exceptions: [item] })
    const wrapper = render(PayrollExceptionsTab)
    await flushPromises()
    expect(buttons(wrapper)).toContain('批准')
    expect(buttons(wrapper)).not.toContain('提出方案')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await state(wrapper).approve(item)
    expect(mocks.wages.approvePayrollException).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    mocks.wages.approvePayrollException.mockRejectedValue(new Error('独立审批失败'))
    await state(wrapper).approve(item)
    expect(mocks.toast).toHaveBeenCalledWith('独立审批失败', 'error')
    expect(state(wrapper).working).toBe(false)
  })

  it('keeps ledger totals free of superseded and voided amounts and export permission', async () => {
    mocks.wages.listPayrollBatches.mockResolvedValue({ batches: [
      { id: 1, status: 'confirmed', payable_wage_cents: 10000, exception_count: 0 },
      { id: 2, status: 'confirmed', superseded_by_batch_id: 1, payable_wage_cents: 9000, exception_count: 2 },
      { id: 3, status: 'voided', payable_wage_cents: 3000, exception_count: 1 },
    ] })
    const reader = render(PayrollLedgerTab)
    await flushPromises()
    expect(state(reader).monthTotal).toBe(10000)
    expect(state(reader).pendingExceptions).toBe(3)
    expect(buttons(reader)).not.toContain('下载预览')
    mocks.permissions.add('wages:export')
    const exporter = render(PayrollLedgerTab)
    await flushPromises()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    await exporter.findAll('button').find(button => button.text() === '下载预览').trigger('click')
    expect(open).toHaveBeenCalledWith('/api/payroll/batches/1/export', '_blank', 'noopener')
  })

  it('keeps ledger row versions, month filters, confirmation and refresh after action', async () => {
    const reviewBatch = { id: 7, row_version: 2, status: 'review_pending', version: 2, payroll_month: '2026-09' }
    const lockedBatch = { id: 8, row_version: 3, status: 'locked', version: 2, payroll_month: '2026-09' }
    mocks.permissions = new Set(['wages:prepare', 'wages:approve'])
    const wrapper = render(PayrollLedgerTab)
    await flushPromises()
    const vm = state(wrapper)
    vm.month = '2026-09'; vm.status = 'locked'
    await vm.load()
    expect(mocks.wages.listPayrollBatches).toHaveBeenLastCalledWith({ payroll_month: '2026-09', status: 'locked' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await vm.confirmBatch(lockedBatch)
    expect(mocks.wages.confirmPayrollBatch).toHaveBeenCalledWith(8, 3)
    expect(mocks.toast).toHaveBeenCalledWith('批次已确认')
    mocks.wages.lockPayrollBatch.mockRejectedValue(new Error('版本冲突'))
    await vm.lock(reviewBatch)
    expect(mocks.wages.lockPayrollBatch).toHaveBeenCalledWith(7, 2)
    expect(mocks.toast).toHaveBeenCalledWith('版本冲突', 'error')
    expect(vm.working).toBe(false)
  })

  it('blocks negative payroll transitions and hides ordinary revision after settlement', async () => {
    const negativeDraft = { id: 1, status: 'draft', negative_payable_count: 2, exception_count: 0 }
    const negativeReview = { id: 2, status: 'review_pending', negative_payable_count: 1 }
    const negativeLocked = { id: 3, status: 'locked', negative_payable_count: 1 }
    const settled = { id: 4, status: 'confirmed', settlement_status: 'exported' }
    mocks.permissions = new Set(['wages:prepare', 'wages:approve'])
    mocks.wages.listPayrollBatches.mockResolvedValue({
      batches: [negativeDraft, negativeReview, negativeLocked, settled],
    })
    const wrapper = render(PayrollLedgerTab)
    await flushPromises()
    const vm = state(wrapper)

    expect(vm.canSubmit(negativeDraft)).toBe(false)
    expect(vm.canLock(negativeReview)).toBe(false)
    expect(vm.canConfirm(negativeLocked)).toBe(false)
    expect(vm.canRevise(settled)).toBe(false)
    expect(wrapper.text()).toContain('负数应付 2 人，不能提交或结算')
    expect(wrapper.text()).toContain('已进入财务结算')
    expect(buttons(wrapper)).not.toContain('锁定')
    expect(buttons(wrapper)).not.toContain('确认')
    expect(buttons(wrapper)).not.toContain('修订')

    await vm.submit(negativeDraft)
    expect(mocks.toast).toHaveBeenCalledWith('存在 2 名员工应付工资为负数，请修正后重算', 'error')
    await vm.lock(negativeReview)
    expect(mocks.toast).toHaveBeenCalledWith('存在 1 名员工应付工资为负数，请修正后重算', 'error')
    expect(mocks.wages.lockPayrollBatch).not.toHaveBeenCalled()
    const confirm = vi.spyOn(window, 'confirm')
    await vm.confirmBatch(negativeLocked)
    expect(mocks.wages.confirmPayrollBatch).not.toHaveBeenCalled()
    expect(confirm).not.toHaveBeenCalled()
    await vm.revise(settled)
    expect(mocks.toast).toHaveBeenCalledWith('该批次已进入财务结算，请在后续期间通过补差或冲销处理', 'error')
    expect(mocks.wages.revisePayrollBatch).not.toHaveBeenCalled()
  })
})

describe('Task 2D exact pricing and navigation consumers', () => {
  it('does not query coverage without wage permission and matches exact version pairs', async () => {
    localStorage.setItem('wageActiveTab', 'priceversions')
    const reader = render(ProcessWageTab)
    await flushPromises()
    expect(mocks.wages.getRoutePriceVersionReference).not.toHaveBeenCalled()
    reader.unmount()
    mocks.permissions.add('wages:prepare')
    mocks.wages.getRoutePriceVersionReference.mockResolvedValue({ items: [{ route_version_id: 81, process_version_id: 71 }, { route_version_id: 82, process_version_id: 71 }] })
    mocks.wages.listRoutePriceVersions.mockResolvedValue({ versions: [{ id: 1, route_version_id: 81, process_version_id: 71, status: 'approved' }] })
    const viewer = render(ProcessWageTab)
    await flushPromises()
    expect(state(viewer).coveredCount).toBe(1)
    expect(state(viewer).missingCount).toBe(1)
    expect(state(viewer).coverageRows[1].approvedPrice).toBe(null)
  })

  it('keeps historical confirmation props reactive and writes exact reason and idempotency', async () => {
    const wrapper = render(HistoricalPriceConfirmationPanel, { props: { reviews: [], canPrepare: false } })
    const review = { review_id: 41, route: { name: '焊接', version: 3 }, process: { name: '下料', version: 2 }, affected_orders: [{ order_no: '26090101', product_code: 'AB' }], drafts: [] }
    await wrapper.setProps({ reviews: [review], canPrepare: true })
    const vm = state(wrapper)
    vm.openCreate(review)
    await vm.createDraft()
    expect(mocks.wages.createHistoricalPriceManualDraft).not.toHaveBeenCalled()
    Object.assign(vm.form, { normal_unit_price: '1.2500', valid_from: '2026-09-01T07:00', rework_rate_percent: '50', confirmation_reason: '历史证据' })
    await vm.createDraft()
    expect(mocks.wages.createHistoricalPriceManualDraft).toHaveBeenCalledWith(41, expect.objectContaining({ normal_unit_price: '1.2500', valid_from: '2026-09-01 07:00:00', valid_to: null, rework_rate_percent: 50, confirmation_reason: '历史证据', idempotency_key: expect.stringMatching(/^historical-price-draft:41:/) }))
    expect(wrapper.emitted('refresh')).toHaveLength(1)
    expect(vm.editorOpen).toBe(false)
  })

  it('keeps historical independent approval cancellation and row version', async () => {
    const wrapper = render(HistoricalPriceConfirmationPanel)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await state(wrapper).approveDraft({ id: 7, row_version: 2 })
    expect(mocks.wages.approveHistoricalPriceManualDraft).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    await state(wrapper).approveDraft({ id: 7, row_version: 2 })
    expect(mocks.wages.approveHistoricalPriceManualDraft).toHaveBeenCalledWith(7, expect.objectContaining({ row_version: 2, idempotency_key: expect.stringMatching(/^historical-price-approve:7:/) }))
  })

  it('hydrates a replacement draft and keeps editor errors open', async () => {
    const wrapper = render(PriceVersionEditor, { props: { open: true, reference: { reference_key: '81:71' } } })
    await wrapper.setProps({ draftPrice: { id: 9, normal_unit_price_micros: 125000, rework_rate_configured: true, rework_rate_basis_points: 5000, valid_from: '2026-09-01 07:00:00', remark: '依据' } })
    const vm = state(wrapper)
    expect(vm.form.normal_unit_price).toBe('12.5000')
    expect(vm.form.rework_rate_percent).toBe('50.00')
    vm.form.rework_rate_percent = '101'
    await vm.submitCreate()
    expect(mocks.wages.createRoutePriceVersion).not.toHaveBeenCalled()
    vm.form.rework_rate_percent = '50'
    mocks.wages.createRoutePriceVersion.mockRejectedValue(new Error('版本已变化'))
    await vm.submitCreate()
    expect(mocks.toast).toHaveBeenCalledWith('版本已变化', 'error')
    expect(wrapper.emitted('created')).toBeUndefined()
    expect(vm.busy).toBe(false)
  })

  it('keeps route category, legacy price payload and versioned-price navigation', async () => {
    mocks.permissions.add('prices:edit')
    const wrapper = render(PriceList)
    await flushPromises()
    expect(mocks.routes.listProcessRoutes).toHaveBeenCalledWith({ category: '结构件' })
    expect(state(wrapper).canEdit).toBe(true)
    await state(wrapper).toggleRoute(8)
    await flushPromises()
    state(wrapper).editPrices[7] = '3.25'
    Object.assign(state(wrapper).editMeta[8], { effectiveDate: '2026-09-01', remark: '依据' })
    await state(wrapper).saveRoute()
    expect(mocks.pricing.saveRouteLevelPricing).toHaveBeenCalledWith(8, { prices: { 7: 3.25 }, effective_date: '2026-09-01', remark: '依据' })
    state(wrapper).openVersionedPricing()
    expect(localStorage.getItem('wageActiveTab')).toBe('priceversions')
    expect(mocks.navigate).toHaveBeenCalledWith('wages')
  })

  it('keeps exact-version navigation intent when entering wages', () => {
    mocks.permissions.add('wages:prepare')
    mocks.router.params = { wage_tab: 'priceversions', route_version_id: '81', process_version_id: '71', create_price: true }
    // Child tabs have their own API/permission protection tests; this checks parent intent.
    const wrapper = render(WageList, { shallow: true })
    expect(state(wrapper).activeTab).toBe('priceversions')
    expect(state(wrapper).priceIntent).toEqual({ route_version_id: 81, process_version_id: 71, create_price: true })
  })
})
