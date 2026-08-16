import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ProcessList from '@/views/ProcessList.vue'


const mocks = vi.hoisted(() => ({
  listProcesses: vi.fn(),
  listProcessVersions: vi.fn(),
  getProcessVersionImpact: vi.fn(),
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


describe('ProcessList loading', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.listProcesses.mockReset()
    mocks.listProcessVersions.mockReset()
    mocks.getProcessVersionImpact.mockReset()
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
    expect(mocks.createProcessRevision).toHaveBeenCalledWith(7, expect.objectContaining({
      row_version: 4,
      revision_reason: '调整精加工参数',
      name: '精车',
      category: '机加工',
      idempotency_key: expect.stringMatching(/^process-revision:/),
    }))
  })
})
