import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PayrollSettlementTab from '@/views/wage/PayrollSettlementTab.vue'

const mocks = vi.hoisted(() => ({
  wages: {},
  auth: { user: { id: 17 } },
  permissions: new Set(),
  toast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({ api: { domains: { wages: mocks.wages } } }))
vi.mock('@/lib/auth.js', () => ({
  auth: mocks.auth,
  can: permission => mocks.permissions.has(permission),
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.toast }))

const batch = {
  id: 31,
  payroll_month: '2026-09',
  version: 2,
  status: 'confirmed',
  payable_wage_cents: 12500,
  prepared_by_name: '财务制单员',
}

function settlement(overrides = {}) {
  return {
    id: 51,
    batch_id: batch.id,
    status: 'not_exported',
    expected_total_cents: batch.payable_wage_cents,
    successful_paid_cents: 0,
    difference_cents: batch.payable_wage_cents,
    blocking_difference_count: 0,
    receipt_batches: [],
    current_export: null,
    latest_reconciliation: null,
    can_close: false,
    row_version: 4,
    ...overrides,
  }
}

function mountTab() {
  return mount(PayrollSettlementTab)
}

describe('payroll settlement workspace', () => {
  beforeEach(() => {
    sessionStorage.removeItem('payroll-settlement:pending-idempotency-keys:17')
    mocks.permissions = new Set([
      'wages:view_all', 'wages:export', 'wages:receipt', 'wages:reconcile', 'wages:close',
    ])
    mocks.toast.mockReset()
    mocks.wages.listPayrollBatches = vi.fn().mockResolvedValue({ batches: [batch] })
    mocks.wages.getPayrollSettlement = vi.fn().mockResolvedValue(settlement())
    mocks.wages.createPayrollSettlementExport = vi.fn().mockResolvedValue({
      id: 71, export_version: 1, replayed: false,
    })
    mocks.wages.uploadPayrollSettlementReceipt = vi.fn().mockResolvedValue({ id: 81 })
    mocks.wages.reconcilePayrollSettlement = vi.fn().mockResolvedValue({
      status: 'difference_pending', blocking_count: 1,
    })
    mocks.wages.resolvePayrollSettlementDifference = vi.fn().mockResolvedValue({ ok: true })
    mocks.wages.closePayrollSettlement = vi.fn().mockResolvedValue({ id: 91 })
    mocks.wages.payrollSettlementExportDownloadUrl = vi.fn(id => `/api/payroll/settlement/exports/${id}/download`)
  })

  it('loads confirmed batches and labels generated files as official payment lists', async () => {
    const wrapper = mountTab()
    await flushPromises()

    expect(mocks.wages.listPayrollBatches).toHaveBeenCalledWith({
      payroll_month: expect.stringMatching(/^\d{4}-\d{2}$/),
      status: 'confirmed',
    })
    expect(wrapper.text()).toContain('此处只生成支付清单并登记财务回执')
    expect(wrapper.text()).toContain('2026-09 / V2')
    expect(wrapper.text()).toContain('¥125.00')
    expect(wrapper.get('[data-testid="create-payment-list"]').text()).toContain('生成支付清单')
    expect(wrapper.find('[data-testid="close-settlement"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('hides the payment-list download link without export permission', async () => {
    mocks.permissions.delete('wages:export')
    mocks.wages.getPayrollSettlement.mockResolvedValue(settlement({
      status: 'exported',
      current_export: { id: 71, export_version: 1, row_count: 4, content_sha256: 'abc123' },
    }))
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.find('[data-testid="download-payment-list"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('ignores an older batch detail response after a faster selection completes', async () => {
    const secondBatch = {
      ...batch,
      id: 32,
      payroll_month: '2026-10',
      payable_wage_cents: 20000,
    }
    mocks.wages.listPayrollBatches.mockResolvedValue({ batches: [batch, secondBatch] })
    const wrapper = mountTab()
    await flushPromises()

    let resolveFirst
    let resolveSecond
    const firstRequest = new Promise(resolve => { resolveFirst = resolve })
    const secondRequest = new Promise(resolve => { resolveSecond = resolve })
    mocks.wages.getPayrollSettlement
      .mockImplementationOnce(() => firstRequest)
      .mockImplementationOnce(() => secondRequest)

    const options = wrapper.findAll('.settlement-batch-option')
    await options[0].trigger('click')
    await options[1].trigger('click')

    resolveSecond(settlement({
      id: 52,
      batch_id: secondBatch.id,
      expected_total_cents: secondBatch.payable_wage_cents,
      current_export: { id: 72, export_version: 1, row_count: 1, content_sha256: 'second' },
    }))
    await flushPromises()
    expect(wrapper.get('.settlement-detail-header h4').text()).toContain('2026-10')
    expect(wrapper.get('[data-testid="download-payment-list"]').attributes('href'))
      .toBe('/api/payroll/settlement/exports/72/download')

    resolveFirst(settlement({
      id: 51,
      batch_id: batch.id,
      current_export: { id: 71, export_version: 1, row_count: 1, content_sha256: 'first' },
    }))
    await flushPromises()
    expect(wrapper.get('.settlement-detail-header h4').text()).toContain('2026-10')
    expect(wrapper.get('[data-testid="download-payment-list"]').attributes('href'))
      .toBe('/api/payroll/settlement/exports/72/download')
    wrapper.unmount()
  })

  it('creates a payment list with an idempotency key and exposes its download link', async () => {
    mocks.wages.getPayrollSettlement
      .mockResolvedValueOnce(settlement())
      .mockResolvedValue(settlement({
        status: 'exported',
        current_export: {
          id: 71, export_version: 1, row_count: 4, content_sha256: 'abc123',
        },
      }))
    const wrapper = mountTab()
    await flushPromises()

    await wrapper.get('[data-testid="create-payment-list"]').trigger('click')
    await flushPromises()

    expect(mocks.wages.createPayrollSettlementExport).toHaveBeenCalledWith(31, {
      idempotency_key: expect.stringMatching(/^payroll-settlement-ui:export:/),
    })
    expect(wrapper.get('[data-testid="download-payment-list"]').attributes('href'))
      .toBe('/api/payroll/settlement/exports/71/download')
    expect(wrapper.text()).toContain('正式支付清单')
    wrapper.unmount()
  })

  it('reuses the payment-list idempotency key after remounting from an uncertain failure', async () => {
    mocks.wages.getPayrollSettlement
      .mockResolvedValueOnce(settlement())
      .mockResolvedValue(settlement({
        status: 'exported',
        current_export: {
          id: 71, export_version: 1, row_count: 4, content_sha256: 'abc123',
        },
      }))
    mocks.wages.createPayrollSettlementExport
      .mockRejectedValueOnce(new Error('网络连接中断，结果未知'))
      .mockResolvedValueOnce({ id: 71, export_version: 1, replayed: true })
    const wrapper = mountTab()
    await flushPromises()

    await wrapper.get('[data-testid="create-payment-list"]').trigger('click')
    await flushPromises()
    wrapper.unmount()

    const retryWrapper = mountTab()
    await flushPromises()
    await retryWrapper.get('[data-testid="create-payment-list"]').trigger('click')
    await flushPromises()

    expect(mocks.wages.createPayrollSettlementExport).toHaveBeenCalledTimes(2)
    const firstKey = mocks.wages.createPayrollSettlementExport.mock.calls[0][1].idempotency_key
    const secondKey = mocks.wages.createPayrollSettlementExport.mock.calls[1][1].idempotency_key
    expect(firstKey).toMatch(/^payroll-settlement-ui:export:/)
    expect(secondKey).toBe(firstKey)
    expect(mocks.toast).toHaveBeenCalledWith('网络连接中断，结果未知', 'error')
    expect(retryWrapper.get('[data-testid="download-payment-list"]').attributes('href'))
      .toBe('/api/payroll/settlement/exports/71/download')
    expect(sessionStorage.getItem('payroll-settlement:pending-idempotency-keys:17'))
      .toBeNull()
    retryWrapper.unmount()
  })

  it('uploads a selected receipt as multipart data and then enables reconciliation', async () => {
    mocks.wages.getPayrollSettlement.mockResolvedValue(settlement({
      status: 'exported',
      current_export: { id: 71, export_version: 1, row_count: 4, content_sha256: 'abc123' },
    }))
    const wrapper = mountTab()
    await flushPromises()
    const file = new File(['payment_reference,employee_no,employee_name,paid_amount,payment_status\n'], 'receipt.csv', {
      type: 'text/csv',
    })
    const receiptInput = wrapper.get('[data-testid="receipt-file"]')
    Object.defineProperty(receiptInput.element, 'files', {
      configurable: true,
      value: [file],
    })
    await receiptInput.trigger('change')
    await wrapper.get('[data-testid="upload-receipt"]').trigger('click')
    await flushPromises()

    expect(mocks.wages.uploadPayrollSettlementReceipt).toHaveBeenCalledTimes(1)
    const [exportId, formData] = mocks.wages.uploadPayrollSettlementReceipt.mock.calls[0]
    expect(exportId).toBe(71)
    expect(formData.get('file').name).toBe('receipt.csv')
    expect(formData.get('idempotency_key')).toMatch(/^payroll-settlement-ui:receipt:/)
    wrapper.unmount()
  })

  it('records supported difference resolutions with a reason and source receipt', async () => {
    mocks.wages.getPayrollSettlement.mockResolvedValue(settlement({
      status: 'difference_pending',
      current_export: { id: 71, export_version: 1, row_count: 4, content_sha256: 'abc123' },
      receipt_batches: [{ id: 81, status: 'accepted', accepted_row_count: 4, failed_row_count: 0 }],
      latest_reconciliation: {
        run_version: 1,
        status: 'difference_pending',
        blocking_count: 1,
        items: [{
          id: 61,
          difference_type: 'duplicate_success',
          payment_reference: 'PAY-1',
          expected_cents: 10000,
          successful_paid_cents: 20000,
          difference_cents: -10000,
          blocking: 1,
          detail_json: JSON.stringify({ receipt_item_id: 92 }),
        }],
      },
    }))
    const wrapper = mountTab()
    await flushPromises()
    await wrapper.get('[aria-label="差异 61 处理原因"]').setValue('财务已核实为重复回执')
    await wrapper.get('[data-testid="settlement-difference-61"] button').trigger('click')
    await flushPromises()

    expect(mocks.wages.resolvePayrollSettlementDifference).toHaveBeenCalledWith(61, {
      resolution_code: 'exclude_duplicate',
      resolution_reason: '财务已核实为重复回执',
      receipt_item_id: 92,
      idempotency_key: expect.stringMatching(/^payroll-settlement-ui:difference:/),
    })
    wrapper.unmount()
  })

  it('shows every export version and filters differences by type, blocking state, and employee', async () => {
    mocks.wages.getPayrollSettlement.mockResolvedValue(settlement({
      status: 'difference_pending',
      current_export: {
        id: 72, export_version: 2, row_count: 4, total_cents: 12500,
        content_sha256: 'current-digest', created_at: '2026-09-03 09:00:00',
      },
      exports: [
        { id: 72, export_version: 2, status: 'active', row_count: 4, total_cents: 12500 },
        { id: 71, export_version: 1, status: 'superseded', row_count: 4, total_cents: 12500 },
      ],
      receipt_batches: [{ id: 81, status: 'accepted', accepted_row_count: 4, failed_row_count: 0 }],
      latest_reconciliation: {
        run_version: 2,
        status: 'difference_pending',
        blocking_count: 1,
        items: [
          {
            id: 61, difference_type: 'underpaid', payment_reference: 'PAY-EMP-1',
            employee_no_snapshot: 'EMP-001', employee_name_snapshot: '张三',
            expected_cents: 10000, successful_paid_cents: 8000, difference_cents: 2000,
            blocking: 1, detail_json: '{}',
          },
          {
            id: 62, difference_type: 'unknown_reference', payment_reference: 'PAY-UNKNOWN',
            expected_cents: 0, successful_paid_cents: 0, difference_cents: 0,
            blocking: 0, detail_json: '{}',
          },
        ],
      },
    }))
    const wrapper = mountTab()
    await flushPromises()

    const versions = wrapper.get('[data-testid="export-version-list"]')
    expect(versions.text()).toContain('V2')
    expect(versions.text()).toContain('当前有效')
    expect(versions.text()).toContain('V1')
    expect(versions.text()).toContain('已被替代')
    expect(wrapper.find('[data-testid="settlement-difference-61"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="settlement-difference-62"]').exists()).toBe(true)

    await wrapper.get('[data-testid="difference-type-filter"]').setValue('underpaid')
    expect(wrapper.find('[data-testid="settlement-difference-61"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="settlement-difference-62"]').exists()).toBe(false)
    await wrapper.get('[data-testid="blocking-filter"]').setValue('informational')
    expect(wrapper.text()).toContain('没有符合当前筛选条件的差异')
    await wrapper.get('[data-testid="difference-type-filter"]').setValue('all')
    expect(wrapper.find('[data-testid="settlement-difference-62"]').exists()).toBe(true)
    await wrapper.get('[data-testid="blocking-filter"]').setValue('all')
    await wrapper.get('[data-testid="employee-filter"]').setValue('张三')
    expect(wrapper.find('[data-testid="settlement-difference-61"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="settlement-difference-62"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows and confirms the final close summary before locking the settlement', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('财务核对完成')
    mocks.wages.getPayrollSettlement.mockResolvedValue(settlement({
      status: 'reconciled',
      successful_paid_cents: 12500,
      difference_cents: 0,
      current_export: {
        id: 72, export_version: 2, row_count: 4, total_cents: 12500,
        content_sha256: 'current-digest',
      },
      exports: [{ id: 72, export_version: 2, status: 'active', row_count: 4, total_cents: 12500 }],
      receipt_batches: [{ id: 81 }, { id: 82 }],
      latest_reconciliation: { run_version: 3, status: 'reconciled', blocking_count: 0, items: [] },
      can_close: true,
    }))
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.get('[data-testid="close-summary"]').text()).toContain('最终金额 ¥125.00')
    expect(wrapper.get('[data-testid="close-summary"]').text()).toContain('当前导出版本 V2')
    expect(wrapper.get('[data-testid="close-summary"]').text()).toContain('回执批次数量 2')
    expect(wrapper.get('[data-testid="close-summary"]').text()).toContain('对账运行版本 第 3 次')
    await wrapper.get('[data-testid="close-settlement"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('最终金额：¥125.00'))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('当前导出版本：V2'))
    expect(mocks.wages.closePayrollSettlement).toHaveBeenCalledWith(51, {
      row_version: 4,
      close_reason: '财务核对完成',
      idempotency_key: expect.stringMatching(/^payroll-settlement-ui:close:/),
    })
    confirm.mockRestore()
    prompt.mockRestore()
    wrapper.unmount()
  })

  it('hides settlement actions from a self-view-only employee', async () => {
    mocks.permissions = new Set(['wages:view_self'])
    const wrapper = mountTab()
    await flushPromises()

    expect(mocks.wages.listPayrollBatches).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="settlement-no-batch"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="create-payment-list"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
