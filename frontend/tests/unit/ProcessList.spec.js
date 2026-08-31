import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ProcessList from '@/views/ProcessList.vue'


const mocks = vi.hoisted(() => ({
  listProcesses: vi.fn(),
  listProcessVersions: vi.fn(),
  getProcessVersionImpact: vi.fn(),
  createVersionedProcess: vi.fn(),
  createProcessRevision: vi.fn(),
  updateProcessVersion: vi.fn(),
  submitProcessVersion: vi.fn(),
  approveProcessVersion: vi.fn(),
  rejectProcessVersion: vi.fn(),
  requestProcessRetirement: vi.fn(),
  requestProcessReactivation: vi.fn(),
  showToast: vi.fn(),
  can: vi.fn(() => true),
  router: { page: 'all-processes' },
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      processes: { listProcesses: mocks.listProcesses },
      processVersions: {
        listProcessVersions: mocks.listProcessVersions,
        getProcessVersionImpact: mocks.getProcessVersionImpact,
        createVersionedProcess: mocks.createVersionedProcess,
        createProcessRevision: mocks.createProcessRevision,
        updateProcessVersion: mocks.updateProcessVersion,
        submitProcessVersion: mocks.submitProcessVersion,
        approveProcessVersion: mocks.approveProcessVersion,
        rejectProcessVersion: mocks.rejectProcessVersion,
        requestProcessRetirement: mocks.requestProcessRetirement,
        requestProcessReactivation: mocks.requestProcessReactivation,
      },
    },
  },
}))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))
vi.mock('@/lib/auth.js', () => ({ can: mocks.can }))
vi.mock('@/lib/router.js', () => ({ router: mocks.router }))

const processRow = {
  id: 7,
  process_code: 'PROC-0007',
  process_name: '精车',
  description: '精加工',
  category: '机加工',
  status: 'active',
  lifecycle_status: 'active',
  process_version: 1,
  version_status: 'published',
  seq_order: 20,
}

const publishedVersion = {
  id: 71,
  process_id: 7,
  version: 1,
  name: '精车',
  description: '精加工',
  category: '机加工',
  seq_order: 20,
  status: 'published',
  row_version: 2,
  created_by_name: '制单人',
  revision_reason: '历史基线',
}

function processDetail(versions = [publishedVersion]) {
  return {
    process: {
      id: 7,
      process_code: 'PROC-0007',
      lifecycle_status: 'active',
      current_effective_version_id: 71,
      row_version: 4,
    },
    versions,
    events: [],
  }
}

function seedList(row = processRow) {
  mocks.listProcesses.mockResolvedValue({
    processes: [row],
    total: 1,
    category_counts: { '结构件': 0, '机加工': 1 },
  })
}

function button(wrapper, label) {
  const match = wrapper.findAll('button').find((item) => item.text() === label)
  expect(match, `missing button: ${label}`).toBeTruthy()
  return match
}

async function mountDetail(versions, rootOverrides = {}) {
  seedList()
  mocks.listProcessVersions.mockResolvedValue({
    ...processDetail(versions),
    process: { ...processDetail(versions).process, ...rootOverrides },
  })
  const wrapper = mount(ProcessList)
  await flushPromises()
  await button(wrapper, '查看版本').trigger('click')
  await flushPromises()
  return wrapper
}


describe('ProcessList loading', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.listProcesses.mockReset()
    mocks.listProcessVersions.mockReset()
    mocks.getProcessVersionImpact.mockReset()
    mocks.createVersionedProcess.mockReset()
    mocks.createProcessRevision.mockReset()
    mocks.updateProcessVersion.mockReset()
    mocks.submitProcessVersion.mockReset()
    mocks.approveProcessVersion.mockReset()
    mocks.rejectProcessVersion.mockReset()
    mocks.requestProcessRetirement.mockReset()
    mocks.requestProcessReactivation.mockReset()
    mocks.showToast.mockReset()
    mocks.can.mockReset()
    mocks.can.mockReturnValue(true)
    mocks.router.page = 'all-processes'
    mocks.getProcessVersionImpact.mockResolvedValue({
      impact: {
        total_references: 2,
        references: [{
          key: 'business-price-reference',
          label: '工价版本',
          count: 2,
          impact_level: 'high',
          suggested_action: '发布前确认工价处置',
        }],
      },
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('retries the initial request and only reports an error after all attempts fail', async () => {
    mocks.listProcesses
      .mockRejectedValueOnce(new Error('temporary one'))
      .mockRejectedValueOnce(new Error('temporary two'))
      .mockResolvedValueOnce({
        processes: [{
          id: 1,
          process_name: '喷漆',
          category: '结构件',
          status: 'active',
          seq_order: 1,
        }],
        total: 1,
        category_counts: { '结构件': 1, '机加工': 0 },
      })

    const wrapper = mount(ProcessList)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(mocks.listProcesses).toHaveBeenCalledTimes(3)
    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('喷漆')
    expect(wrapper.text()).toContain('工序总数')
  })

  it('shows stable identity, switches versions, and keeps a published version read-only', async () => {
    const pendingVersion = {
      ...publishedVersion,
      id: 72,
      version: 2,
      status: 'pending_approval',
      row_version: 3,
      supersedes_version_id: 71,
      name: '精车二序',
      revision_reason: '调整精加工参数',
    }
    mocks.listProcesses.mockResolvedValue({
      processes: [{ ...processRow, open_version_status: 'pending_approval' }],
      total: 1,
      category_counts: { '结构件': 0, '机加工': 1 },
    })
    mocks.listProcessVersions.mockResolvedValue(processDetail([publishedVersion, pendingVersion]))

    const wrapper = mount(ProcessList)
    await flushPromises()

    expect(wrapper.text()).toContain('PROC-0007')
    expect(wrapper.text()).toContain('待审批')
    const viewButton = wrapper.findAll('button').find((button) => button.text() === '查看版本')
    await viewButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('工价版本')
    expect(wrapper.text()).toContain('发布前确认工价处置')
    const currentButton = wrapper.findAll('button').find((button) => button.text() === '当前版本 V1')
    await currentButton.trigger('click')
    await flushPromises()

    const editorInputs = wrapper.findAll('.version-editor input')
    expect(editorInputs.length).toBeGreaterThan(0)
    expect(editorInputs.every((input) => input.attributes('disabled') !== undefined)).toBe(true)
  })

  it('creates a revision through the version API with root concurrency data', async () => {
    const draftVersion = {
      ...publishedVersion,
      id: 72,
      version: 2,
      status: 'draft',
      row_version: 0,
      supersedes_version_id: 71,
      revision_reason: '调整精加工参数',
    }
    mocks.listProcesses.mockResolvedValue({
      processes: [processRow],
      total: 1,
      category_counts: { '结构件': 0, '机加工': 1 },
    })
    mocks.listProcessVersions
      .mockResolvedValueOnce(processDetail())
      .mockResolvedValue(processDetail([publishedVersion, draftVersion]))
    mocks.createProcessRevision.mockResolvedValue(draftVersion)

    const wrapper = mount(ProcessList)
    await flushPromises()

    const createRevisionButton = wrapper.findAll('button').find((button) => button.text() === '创建修订版')
    await createRevisionButton.trigger('click')
    await flushPromises()
    await wrapper.find('.command-modal textarea').setValue('调整精加工参数')
    const confirmButton = wrapper.findAll('.command-modal button').find((button) => button.text() === '创建修订版')
    await confirmButton.trigger('click')
    await flushPromises()

    expect(mocks.createProcessRevision).toHaveBeenCalledOnce()
    const [processId, revisionPayload] = mocks.createProcessRevision.mock.calls[0]
    expect(processId).toBe(7)
    expect(revisionPayload).toEqual(expect.objectContaining({
      row_version: 4,
      revision_reason: '调整精加工参数',
      name: '精车',
      category: '机加工',
      idempotency_key: expect.stringMatching(/^process-revision:/),
    }))
    expect(mocks.showToast).toHaveBeenCalledWith('修订版草稿已创建')
  })

  it('creates a V1 draft, opens its detail, toasts, and reloads the list', async () => {
    seedList()
    const root = {
      id: 8,
      process_code: 'PROC-0008',
      lifecycle_status: 'active',
      current_effective_version_id: null,
      row_version: 0,
    }
    const version = {
      ...publishedVersion,
      id: 81,
      process_id: 8,
      version: 1,
      status: 'draft',
      row_version: 0,
      name: '外圆磨',
      revision_reason: '新增磨削工艺',
    }
    mocks.createVersionedProcess.mockResolvedValue({ root, version })
    mocks.listProcessVersions.mockResolvedValue({ process: root, versions: [version], events: [] })

    const wrapper = mount(ProcessList)
    await flushPromises()
    await button(wrapper, '新建工序').trigger('click')
    await wrapper.find('.process-form-modal input[placeholder]').setValue('外圆磨')
    const textareas = wrapper.findAll('.process-form-modal textarea')
    await textareas[0].setValue('磨削外圆')
    await textareas[1].setValue('新增磨削工艺')
    await button(wrapper, '创建 V1 草稿').trigger('click')
    await flushPromises()

    const [createPayload] = mocks.createVersionedProcess.mock.calls[0]
    expect(createPayload).toEqual(expect.objectContaining({
      name: '外圆磨',
      category: '结构件',
      description: '磨削外圆',
      seq_order: 0,
      revision_reason: '新增磨削工艺',
      idempotency_key: expect.stringMatching(/^process-create:/),
    }))
    expect(mocks.showToast).toHaveBeenCalledWith('V1 草稿已创建')
    expect(wrapper.text()).toContain('PROC-0008')
  })

  it('saves a draft with row concurrency data and refreshes detail before list reload', async () => {
    const draft = {
      ...publishedVersion,
      id: 72,
      version: 2,
      status: 'draft',
      row_version: 3,
      supersedes_version_id: 71,
    }
    mocks.updateProcessVersion.mockResolvedValue({ ...draft, row_version: 4, name: '精车二序' })
    const wrapper = await mountDetail([publishedVersion, draft])

    await wrapper.find('.version-editor input').setValue('精车二序')
    await button(wrapper, '保存草稿').trigger('click')
    await flushPromises()

    const [versionId, updatePayload] = mocks.updateProcessVersion.mock.calls[0]
    expect(versionId).toBe(72)
    expect(updatePayload).toEqual({
      row_version: 3,
      name: '精车二序',
      category: '机加工',
      description: '精加工',
      seq_order: 20,
    })
    expect(mocks.showToast).toHaveBeenCalledWith('草稿已保存')
    expect(wrapper.text()).toContain('草稿可编辑')
  })

  it('submits an unchanged draft with an idempotency key and row version', async () => {
    const draft = {
      ...publishedVersion,
      id: 72,
      version: 2,
      status: 'draft',
      row_version: 3,
      supersedes_version_id: 71,
    }
    mocks.submitProcessVersion.mockResolvedValue({
      ...draft,
      status: 'pending_approval',
      row_version: 4,
    })
    const wrapper = await mountDetail([publishedVersion, draft])

    await button(wrapper, '提交审批').trigger('click')
    await flushPromises()

    expect(mocks.submitProcessVersion).toHaveBeenCalledWith(72, {
      row_version: 3,
      idempotency_key: expect.stringMatching(/^process-submit:/),
    })
    expect(mocks.showToast).toHaveBeenCalledWith('版本已提交审批')
    expect(wrapper.text()).toContain('草稿可编辑')
  })

  it('approves a pending version with the frozen transition payload', async () => {
    const pending = {
      ...publishedVersion,
      id: 72,
      version: 2,
      status: 'pending_approval',
      row_version: 4,
      supersedes_version_id: 71,
    }
    mocks.approveProcessVersion.mockResolvedValue({
      ...pending,
      status: 'published',
      row_version: 5,
    })
    const wrapper = await mountDetail([publishedVersion, pending])

    await button(wrapper, '批准并发布').trigger('click')
    await flushPromises()

    expect(mocks.approveProcessVersion).toHaveBeenCalledWith(72, {
      row_version: 4,
      idempotency_key: expect.stringMatching(/^process-approve:/),
    })
    expect(mocks.showToast).toHaveBeenCalledWith('版本已批准并发布')
  })

  it('validates and submits a rejection reason without closing early', async () => {
    const pending = {
      ...publishedVersion,
      id: 72,
      version: 2,
      status: 'pending_approval',
      row_version: 4,
      supersedes_version_id: 71,
    }
    mocks.rejectProcessVersion.mockResolvedValue({
      ...pending,
      status: 'rejected',
      row_version: 5,
    })
    const wrapper = await mountDetail([publishedVersion, pending])

    await button(wrapper, '驳回').trigger('click')
    await button(wrapper, '确认驳回').trigger('click')
    expect(mocks.showToast).toHaveBeenLastCalledWith('请填写至少 2 个字符的驳回原因', 'error')
    expect(mocks.rejectProcessVersion).not.toHaveBeenCalled()

    await wrapper.find('.command-modal textarea').setValue('工艺参数不完整')
    await button(wrapper, '确认驳回').trigger('click')
    await flushPromises()

    expect(mocks.rejectProcessVersion).toHaveBeenCalledWith(72, {
      row_version: 4,
      idempotency_key: expect.stringMatching(/^process-reject:/),
      reason: '工艺参数不完整',
    })
    expect(mocks.showToast).toHaveBeenCalledWith('版本已驳回')
  })

  it.each([
    ['active', '申请退休', mocks.requestProcessRetirement, /^process-retire:/, '退休申请已提交'],
    ['retired', '申请重新启用', mocks.requestProcessReactivation, /^process-reactivate:/, '重新启用申请已提交'],
  ])('submits the %s lifecycle command with root concurrency data', async (
    lifecycleStatus, label, apiMethod, keyPattern, toast,
  ) => {
    apiMethod.mockResolvedValue({ id: 91 })
    const wrapper = await mountDetail(
      [publishedVersion],
      { lifecycle_status: lifecycleStatus },
    )

    const matchingButtons = wrapper.findAll('button').filter((item) => item.text() === label)
    await matchingButtons[matchingButtons.length - 1].trigger('click')
    await wrapper.find('.command-modal textarea').setValue('生命周期受控申请')
    await button(wrapper, '提交申请').trigger('click')
    await flushPromises()

    expect(apiMethod).toHaveBeenCalledWith(7, {
      row_version: 4,
      reason: '生命周期受控申请',
      idempotency_key: expect.stringMatching(keyPattern),
    })
    expect(mocks.showToast).toHaveBeenCalledWith(toast)
  })

  it('keeps read access while hiding every command denied by permission checks', async () => {
    mocks.can.mockReturnValue(false)
    seedList()
    mocks.listProcessVersions.mockResolvedValue(processDetail())
    const wrapper = mount(ProcessList)
    await flushPromises()

    expect(wrapper.text()).toContain('查看版本')
    expect(wrapper.text()).not.toContain('新建工序')
    expect(wrapper.text()).not.toContain('创建修订版')
    expect(wrapper.text()).not.toContain('申请退休')
    await button(wrapper, '查看版本').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已锁定，只读查看')
  })

  it('maps a stale API error, keeps detail open, and does not reload the list', async () => {
    const draft = {
      ...publishedVersion,
      id: 72,
      version: 2,
      status: 'draft',
      row_version: 3,
      supersedes_version_id: 71,
    }
    const stale = Object.assign(new Error('stale'), { action: 'refresh_process_version' })
    mocks.updateProcessVersion.mockRejectedValue(stale)
    const wrapper = await mountDetail([publishedVersion, draft])

    await button(wrapper, '保存草稿').trigger('click')
    await flushPromises()

    expect(mocks.showToast).toHaveBeenCalledWith(
      '数据已被其他操作更新，请刷新版本详情后重试',
      'error',
    )
    expect(mocks.listProcesses).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.version-detail-modal').exists()).toBe(true)

    await wrapper.find('.version-detail-modal .modal-close').trigger('click')
    expect(wrapper.find('.version-detail-modal').exists()).toBe(false)
  })
})
